"""Görüntü kaynakları: webcam, IP kamera (RTSP/HTTP), video dosyası, demo."""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

log = logging.getLogger(__name__)


class SourceError(RuntimeError):
    pass


@dataclass(slots=True)
class Frame:
    image: np.ndarray
    index: int
    timestamp: float = field(default_factory=time.monotonic)
    # Kaynağa özgü ek bilgiler (ör. demo kaynağındaki gerçek plaka)
    meta: dict[str, Any] = field(default_factory=dict)


class FrameSource(ABC):
    #: Canlı kaynaklar (kamera) kendi hızında kare üretir; dosyalar yavaşlatılarak oynatılır.
    live: bool = True

    @property
    def fps(self) -> float | None:
        return None

    @abstractmethod
    def open(self) -> None:
        """Kaynağı açar; açılamazsa :class:`SourceError` fırlatır."""

    @abstractmethod
    def read(self) -> Frame | None:
        """Sonraki kare; akış koptuysa ``None``."""

    def close(self) -> None:  # noqa: B027 - isteğe bağlı
        pass


def describe_source(source: str) -> str:
    text = source.strip()
    if text.isdigit():
        return f"USB/Webcam #{text}"
    if text.lower() == "demo":
        return "Demo (simülasyon)"
    if "://" in text:
        scheme, _, rest = text.partition("://")
        host = rest.split("@")[-1].split("/")[0]  # kullanıcı adı/şifreyi gösterme
        return f"{scheme.upper()} {host}"
    return Path(text).name


class OpenCVSource(FrameSource):
    def __init__(self, source: str, *, loop: bool = True) -> None:
        self.source = source.strip()
        self.loop = loop
        self._capture: cv2.VideoCapture | None = None
        self._index = 0
        self._fps: float | None = None
        self.live = not Path(self.source).is_file()

    @property
    def fps(self) -> float | None:
        return self._fps

    def open(self) -> None:
        self.close()
        if self.source.isdigit():
            capture = cv2.VideoCapture(int(self.source))
        else:
            if self.source.lower().startswith("rtsp://"):
                # RTSP'de UDP paket kayıpları bozuk kare üretir; TCP daha kararlı.
                os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
            capture = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
        if not capture.isOpened():
            capture.release()
            raise SourceError(f"Kaynak açılamadı: {describe_source(self.source)}")
        if self.live:
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        fps = capture.get(cv2.CAP_PROP_FPS)
        self._fps = fps if fps and 1 <= fps <= 120 else None
        self._capture = capture

    def read(self) -> Frame | None:
        if self._capture is None:
            return None
        ok, image = self._capture.read()
        if not ok and not self.live and self.loop:
            self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, image = self._capture.read()
        if not ok or image is None:
            return None
        self._index += 1
        return Frame(image=image, index=self._index)

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
