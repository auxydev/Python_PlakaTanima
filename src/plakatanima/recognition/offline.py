"""Kayıtlı resim ve video dosyaları üzerinde tanıma (komut satırı ve testler için)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import cv2
import numpy as np

from plakatanima.recognition.pipeline import RecognitionPipeline, Roi
from plakatanima.recognition.tracker import ConfirmedPlate, PlateVoter
from plakatanima.recognition.types import FrameAnalysis

IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"})

FrameCallback = Callable[[float, np.ndarray, FrameAnalysis], None]


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_SUFFIXES


def read_image(path: Path) -> np.ndarray:
    # cv2.imread Windows'ta Türkçe karakterli yolları açamaz; baytlardan çöz.
    data = np.fromfile(str(path), dtype=np.uint8)
    frame = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
    if frame is None:
        raise ValueError(f"Resim okunamadı: {path}")
    return frame


def write_image(path: Path, frame: np.ndarray, quality: int = 90) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buffer = cv2.imencode(path.suffix or ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError(f"Resim kaydedilemedi: {path}")
    buffer.tofile(str(path))


def recognize_video(
    pipeline: RecognitionPipeline,
    voter: PlateVoter,
    path: Path,
    *,
    process_fps: float = 4.0,
    roi: Roi | None = None,
    on_frame: FrameCallback | None = None,
) -> Iterator[tuple[float, ConfirmedPlate]]:
    """Videoyu ``process_fps`` hızında örnekleyerek onaylanan plakaları üretir.

    Zaman, videonun kendi zaman çizelgesine göre (saniye) verilir.
    """
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError(f"Video açılamadı: {path}")
    video_fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(round(video_fps / process_fps), 1)
    index = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if index % step == 0:
                timestamp = index / video_fps
                analysis = pipeline.analyze(frame, roi)
                if on_frame is not None:
                    on_frame(timestamp, frame, analysis)
                for confirmed in voter.update(analysis.plates, payload=frame, now=timestamp):
                    yield timestamp, confirmed
            index += 1
    finally:
        capture.release()
