"""Kamera iş parçacıklarından gelen geri çağrıları Qt sinyallerine çevirir.

Sinyaller ana (arayüz) iş parçacığında işlenir. Kareler birleştirilir:
arayüz yavaş kalırsa eski kareler kuyrukta birikmez, yalnızca en sonuncusu çizilir.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal

from plakatanima.camera.runner import CameraCallbacks, CameraStatus
from plakatanima.camera.source import Frame
from plakatanima.recognition.tracker import ConfirmedPlate
from plakatanima.recognition.types import FrameAnalysis
from plakatanima.services.parking import PlateObservation


class CameraBridge(QObject):
    frame_ready = Signal(int, object)  # kamera, np.ndarray
    analysis_ready = Signal(int, object)  # kamera, FrameAnalysis
    plate_confirmed = Signal(int, object, object)  # kamera, PlateObservation, ConfirmedPlate
    status_changed = Signal(int, object, str)  # kamera, CameraStatus, mesaj
    _frame_pending = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._latest: dict[int, Frame] = {}
        self._frame_pending.connect(self._deliver_frame)

    def callbacks(self) -> CameraCallbacks:
        return CameraCallbacks(
            on_frame=self._on_frame,
            on_analysis=self._on_analysis,
            on_plate=self._on_plate,
            on_status=self._on_status,
        )

    def _on_frame(self, index: int, frame: Frame) -> None:
        with self._lock:
            already_pending = index in self._latest
            self._latest[index] = frame
        if not already_pending:
            self._frame_pending.emit(index)

    def _deliver_frame(self, index: int) -> None:
        with self._lock:
            frame = self._latest.pop(index, None)
        if frame is not None:
            self.frame_ready.emit(index, frame.image)

    def _on_analysis(self, index: int, analysis: FrameAnalysis) -> None:
        self.analysis_ready.emit(index, analysis)

    def _on_plate(self, index: int, obs: PlateObservation, confirmed: ConfirmedPlate) -> None:
        self.plate_confirmed.emit(index, obs, confirmed)

    def _on_status(self, index: int, status: CameraStatus, message: str) -> None:
        self.status_changed.emit(index, status, message)
