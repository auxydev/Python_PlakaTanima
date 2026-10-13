"""Kamera başına arka plan işleme.

Her kamera için iki iş parçacığı çalışır:

* **Yakalama**: Kaynaktan sürekli kare okur, en son kareyi saklar ve ekranda
  göstermek için (sınırlı hızda) yayınlar. Sürekli okumak, IP kameralarda
  tamponun dolup görüntünün gecikmesini engeller.
* **Analiz**: ``process_fps`` hızında en son kareyi alır, tanıma yapar,
  okumaları oylar ve onaylanan plakaları anlık görüntüsüyle birlikte bildirir.

Bağlantı koparsa kaynak artan aralıklarla (en çok 30 sn) yeniden açılır.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from plakatanima.camera.snapshot import save_snapshot
from plakatanima.camera.source import Frame, FrameSource, SourceError
from plakatanima.config import CameraConfig
from plakatanima.recognition.tracker import ConfirmedPlate, PlateVoter
from plakatanima.recognition.types import FrameAnalysis
from plakatanima.services.parking import PlateObservation

log = logging.getLogger(__name__)

MAX_RECONNECT_DELAY = 30.0


class FrameAnalyzer(Protocol):
    def analyze_frame(self, frame: Frame, roi) -> FrameAnalysis: ...


class CameraStatus(StrEnum):
    STARTING = "baslatiliyor"
    LOADING = "model_yukleniyor"
    RUNNING = "calisiyor"
    RECONNECTING = "yeniden_baglaniyor"
    ERROR = "hata"
    STOPPED = "durduruldu"

    @property
    def label(self) -> str:
        return {
            CameraStatus.STARTING: "Başlatılıyor",
            CameraStatus.LOADING: "Modeller yükleniyor",
            CameraStatus.RUNNING: "Çalışıyor",
            CameraStatus.RECONNECTING: "Yeniden bağlanıyor",
            CameraStatus.ERROR: "Hata",
            CameraStatus.STOPPED: "Durduruldu",
        }[self]


@dataclass(slots=True)
class CameraCallbacks:
    """Tüm geri çağrılar kameranın iş parçacığından çağrılır."""

    on_frame: Callable[[int, Frame], None] | None = None
    on_analysis: Callable[[int, FrameAnalysis], None] | None = None
    on_plate: Callable[[int, PlateObservation, ConfirmedPlate], None] | None = None
    on_status: Callable[[int, CameraStatus, str], None] | None = None


class CameraRunner:
    def __init__(
        self,
        index: int,
        camera: CameraConfig,
        *,
        source_factory: Callable[[], FrameSource],
        analyzer_factory: Callable[[], FrameAnalyzer],
        voter: PlateVoter,
        callbacks: CameraCallbacks,
        captures_dir: Path | None = None,
        display_fps: float = 20.0,
    ) -> None:
        self.index = index
        self.camera = camera
        self._source_factory = source_factory
        self._analyzer_factory = analyzer_factory
        self._voter = voter
        self._callbacks = callbacks
        self._captures_dir = captures_dir
        self._display_period = 1.0 / display_fps
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest: Frame | None = None
        self._threads: list[threading.Thread] = []
        self.status = CameraStatus.STOPPED
        self.status_message = ""
        self.analysis_ms = 0.0
        self._capture_status = CameraStatus.STARTING
        self._capture_message = ""
        self._analyzer_ready = False
        self._analysis_error: str | None = None

    # ------------------------------------------------------------- yaşam döngüsü
    def start(self) -> None:
        if self.is_running:
            return
        self._stop.clear()
        self._voter.reset()
        self._capture_status = CameraStatus.STARTING
        self._analyzer_ready = False
        self._analysis_error = None
        self._set_status(CameraStatus.STARTING, "")
        self._threads = [
            threading.Thread(target=loop, name=f"cam{self.index}-{name}", daemon=True)
            for name, loop in (("capture", self._capture_loop), ("analysis", self._analysis_loop))
        ]
        for thread in self._threads:
            thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        for thread in self._threads:
            if thread is not threading.current_thread():
                thread.join(timeout)
        self._threads = []
        self._set_status(CameraStatus.STOPPED, "")

    @property
    def is_running(self) -> bool:
        return any(t.is_alive() for t in self._threads)

    def latest_frame(self) -> Frame | None:
        with self._lock:
            return self._latest

    def _set_status(self, status: CameraStatus, message: str) -> None:
        if status is self.status and message == self.status_message:
            return
        self.status, self.status_message = status, message
        if status in (CameraStatus.ERROR, CameraStatus.RECONNECTING):
            log.warning("[%s] %s: %s", self.camera.name, status.label, message)
        if self._callbacks.on_status:
            self._callbacks.on_status(self.index, status, message)

    def _update_status(self) -> None:
        """Yakalama ve analiz durumlarını tek bir durumda birleştirir."""
        if self._stop.is_set():
            return
        if self._analysis_error is not None:
            self._set_status(CameraStatus.ERROR, self._analysis_error)
        elif self._capture_status is not CameraStatus.RUNNING:
            self._set_status(self._capture_status, self._capture_message)
        elif not self._analyzer_ready:
            self._set_status(CameraStatus.LOADING, "Tanıma modelleri hazırlanıyor")
        else:
            self._set_status(CameraStatus.RUNNING, "")

    def _set_capture_status(self, status: CameraStatus, message: str = "") -> None:
        self._capture_status, self._capture_message = status, message
        self._update_status()

    # ------------------------------------------------------------- yakalama
    def _capture_loop(self) -> None:
        delay = 1.0
        while not self._stop.is_set():
            source = self._source_factory()
            try:
                source.open()
            except SourceError as exc:
                self._set_capture_status(
                    CameraStatus.RECONNECTING, f"{exc} — {delay:.0f} sn sonra tekrar"
                )
                self._stop.wait(delay)
                delay = min(delay * 2, MAX_RECONNECT_DELAY)
                continue
            delay = 1.0
            self._set_capture_status(CameraStatus.RUNNING)
            try:
                self._read_frames(source)
            except Exception:
                log.exception("[%s] görüntü okunurken hata", self.camera.name)
            finally:
                source.close()
            if not self._stop.is_set():
                self._set_capture_status(CameraStatus.RECONNECTING, "Görüntü akışı kesildi")
                self._stop.wait(delay)

    def _read_frames(self, source: FrameSource) -> None:
        last_display = 0.0
        pace = 1.0 / source.fps if (not source.live and source.fps) else 0.0
        next_due = time.monotonic()
        while not self._stop.is_set():
            frame = source.read()
            if frame is None:
                return
            with self._lock:
                self._latest = frame
            now = time.monotonic()
            if self._callbacks.on_frame and now - last_display >= self._display_period:
                last_display = now
                self._callbacks.on_frame(self.index, frame)
            if pace:
                next_due += pace
                wait = next_due - time.monotonic()
                if wait > 0:
                    self._stop.wait(wait)
                else:
                    next_due = time.monotonic()

    # --------------------------------------------------------------- analiz
    def _analysis_loop(self) -> None:
        try:
            analyzer = self._analyzer_factory()
        except Exception as exc:
            log.exception("[%s] tanıma modelleri yüklenemedi", self.camera.name)
            self._analysis_error = f"Modeller yüklenemedi: {exc}"
            self._update_status()
            return
        self._analyzer_ready = True
        self._update_status()

        last_index = -1
        while not self._stop.is_set():
            started = time.monotonic()
            frame = self.latest_frame()
            if frame is None or frame.index == last_index:
                self._stop.wait(0.02)
                continue
            last_index = frame.index
            try:
                analysis = analyzer.analyze_frame(frame, self.camera.roi)
            except Exception:
                log.exception("[%s] kare analiz edilemedi", self.camera.name)
                self._stop.wait(1.0)
                continue
            self.analysis_ms = analysis.elapsed_ms
            if self._callbacks.on_analysis:
                self._callbacks.on_analysis(self.index, analysis)
            for confirmed in self._voter.update(analysis.plates, payload=frame.image):
                self._emit_plate(confirmed)
            period = 1.0 / self.camera.process_fps
            remaining = period - (time.monotonic() - started)
            if remaining > 0:
                self._stop.wait(remaining)

    def _emit_plate(self, confirmed: ConfirmedPlate) -> None:
        image_path = None
        if self._captures_dir is not None and confirmed.payload is not None:
            try:
                image_path = save_snapshot(
                    self._captures_dir,
                    confirmed.payload,
                    camera_name=self.camera.name,
                    plate=confirmed.plate,
                    plate_bbox=confirmed.best_read.bbox,
                )
            except (OSError, ValueError):
                log.exception("[%s] anlık görüntü kaydedilemedi", self.camera.name)
        observation = PlateObservation(
            plate=confirmed.plate,
            camera_name=self.camera.name,
            role=self.camera.role,
            vehicle_type=confirmed.vehicle_type,
            confidence=round(confirmed.confidence, 4),
            raw_text=confirmed.best_read.raw_text,
            image_path=image_path,
        )
        if self._callbacks.on_plate:
            self._callbacks.on_plate(self.index, observation, confirmed)
