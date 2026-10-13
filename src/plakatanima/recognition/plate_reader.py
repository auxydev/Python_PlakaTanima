"""Plaka tespiti + OCR."""

from __future__ import annotations

import statistics
from abc import ABC, abstractmethod

import numpy as np

from plakatanima.recognition.model_store import ModelError
from plakatanima.recognition.types import BBox, RawPlate
from plakatanima.recognition.vehicle_detector import onnx_providers


class PlateReader(ABC):
    @abstractmethod
    def read(self, frame: np.ndarray) -> list[RawPlate]:
        """BGR karedeki plakaları bulur ve okur."""


def ocr_confidence(text: str, confidence: float | list[float]) -> float:
    """OCR güvenini tek sayıya indirger.

    fast-plate-ocr sabit sayıda karakter yuvası için olasılık döndürür; plaka
    metni ilk yuvalardadır, kalanlar dolgudur. Yalnızca metnin yuvaları dikkate alınır.
    """
    if isinstance(confidence, int | float):
        return float(confidence)
    values = list(confidence)
    if not values:
        return 0.0
    if text and len(values) >= len(text):
        values = values[: len(text)]
    return float(statistics.fmean(values))


class FastAlprPlateReader(PlateReader):
    """`fast-alpr <https://github.com/ankandrew/fast-alpr>`_: YOLOv9 plaka tespiti + CCT OCR.

    Modeller ilk kullanımda indirilir. Küresel OCR modeli Türk plakalarını da okur
    ve plakanın ülkesini (``region``) tahmin eder.
    """

    def __init__(
        self,
        *,
        detector_model: str,
        ocr_model: str,
        detector_confidence: float = 0.4,
        device: str = "auto",
    ) -> None:
        try:
            from fast_alpr import ALPR
        except ImportError as exc:  # pragma: no cover - bağımlılık zorunlu
            raise ModelError("fast-alpr kurulu değil: pip install fast-alpr[onnx]") from exc

        providers = onnx_providers(device)
        try:
            self._alpr = ALPR(
                detector_model=detector_model,
                detector_conf_thresh=detector_confidence,
                detector_providers=providers,
                ocr_model=ocr_model,
                ocr_device="cpu" if device == "cpu" else "auto",
                ocr_providers=providers,
            )
        except Exception as exc:
            raise ModelError(f"Plaka modelleri yüklenemedi: {exc}") from exc

    def read(self, frame: np.ndarray) -> list[RawPlate]:
        plates: list[RawPlate] = []
        for result in self._alpr.predict(frame):
            ocr = result.ocr
            if ocr is None or not ocr.text:
                continue
            box = result.detection.bounding_box
            plates.append(
                RawPlate(
                    bbox=BBox(box.x1, box.y1, box.x2, box.y2),
                    text=ocr.text,
                    confidence=ocr_confidence(ocr.text, ocr.confidence),
                    detection_confidence=float(result.detection.confidence),
                    region=getattr(ocr, "region", None),
                    region_confidence=getattr(ocr, "region_confidence", None),
                )
            )
        return plates
