"""Tek bir karenin analizi: araç tespiti + plaka okuma + plakayı araca eşleme."""

from __future__ import annotations

import time
from dataclasses import replace

import cv2
import numpy as np

from plakatanima.config import RecognitionConfig
from plakatanima.core.plate import format_plate, normalize_plate
from plakatanima.recognition.plate_reader import PlateReader
from plakatanima.recognition.types import (
    BBox,
    FrameAnalysis,
    PlateRead,
    RawPlate,
    VehicleDetection,
)
from plakatanima.recognition.vehicle_detector import VehicleDetector

Roi = tuple[float, float, float, float]

TURKEY_REGIONS = frozenset({"Turkey", "Unknown"})
# OCR modeli plakanın başka bir ülkeye ait olduğunu bu güvenle söylüyorsa
# Türk plakası düzeltmeleri uygulanmaz (ör. Çek plakası "5AU5341" -> "54U5341" olmasın).
FOREIGN_REGION_CONFIDENCE = 0.6


def roi_to_bbox(roi: Roi, width: int, height: int) -> BBox:
    x1, y1, x2, y2 = roi
    return BBox(int(x1 * width), int(y1 * height), int(x2 * width), int(y2 * height))


def match_vehicle(plate: BBox, vehicles: list[VehicleDetection]) -> VehicleDetection | None:
    """Plakanın merkezini içeren en küçük araç kutusu (iç içe kutularda en özel olanı)."""
    cx, cy = plate.center
    containing = [v for v in vehicles if v.bbox.contains(cx, cy)]
    return min(containing, key=lambda v: v.bbox.area) if containing else None


def normalize_raw_plate(raw: RawPlate, *, turkish_only: bool) -> str | None:
    foreign = (
        raw.region is not None
        and raw.region not in TURKEY_REGIONS
        and (raw.region_confidence or 0.0) >= FOREIGN_REGION_CONFIDENCE
    )
    return normalize_plate(raw.text, turkish_only=turkish_only, allow_corrections=not foreign)


class RecognitionPipeline:
    def __init__(
        self,
        vehicle_detector: VehicleDetector,
        plate_reader: PlateReader,
        config: RecognitionConfig,
    ) -> None:
        self.vehicle_detector = vehicle_detector
        self.plate_reader = plate_reader
        # Ayar nesnesi paylaşılır: eşik değişiklikleri yeniden başlatmadan uygulanır.
        self.config = config

    def analyze(self, frame: np.ndarray, roi: Roi | None = None) -> FrameAnalysis:
        started = time.perf_counter()
        work, dx, dy = frame, 0, 0
        if roi is not None:
            box = roi_to_bbox(roi, frame.shape[1], frame.shape[0])
            work, dx, dy = box.crop(frame), box.x1, box.y1

        vehicles = [
            replace(v, bbox=v.bbox.offset(dx, dy)) for v in self.vehicle_detector.detect(work)
        ]
        analysis = FrameAnalysis(vehicles=vehicles)
        for raw in self.plate_reader.read(work):
            raw = replace(raw, bbox=raw.bbox.offset(dx, dy))
            text = normalize_raw_plate(raw, turkish_only=self.config.turkish_plates_only)
            if text is None or raw.confidence < self.config.min_ocr_confidence:
                analysis.rejected.append(raw)
                continue
            analysis.plates.append(
                PlateRead(
                    bbox=raw.bbox,
                    text=text,
                    raw_text=raw.text,
                    confidence=raw.confidence,
                    vehicle=match_vehicle(raw.bbox, vehicles),
                    region=raw.region,
                )
            )
        analysis.elapsed_ms = (time.perf_counter() - started) * 1000
        return analysis

    def analyze_frame(self, frame, roi: Roi | None = None) -> FrameAnalysis:
        """Kamera karesi (``image`` alanı olan nesne) için :meth:`analyze`."""
        return self.analyze(frame.image, roi)


_ASCII = str.maketrans("ÇĞİÖŞÜçğıöşü", "CGIOSUcgiosu")


def _bgr(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return b, g, r


def _label(img: np.ndarray, text: str, x: int, y: int, color: tuple[int, int, int]) -> None:
    text = text.translate(_ASCII)  # OpenCV yazı tipi Türkçe karakter içermez
    scale = max(0.5, min(img.shape[1] / 1400, 1.2))
    thickness = 1 if scale < 0.8 else 2
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    y = max(y, th + base + 4)
    cv2.rectangle(img, (x, y - th - base - 4), (x + tw + 6, y), color, -1)
    cv2.putText(
        img, text, (x + 3, y - base - 2), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255),
        thickness, cv2.LINE_AA,
    )  # fmt: skip


def annotate(frame: np.ndarray, analysis: FrameAnalysis, roi: Roi | None = None) -> np.ndarray:
    """Analiz sonucunu kare üzerine çizer (komut satırı çıktısı için)."""
    img = frame.copy()
    if roi is not None:
        box = roi_to_bbox(roi, img.shape[1], img.shape[0])
        cv2.rectangle(img, (box.x1, box.y1), (box.x2, box.y2), (200, 200, 200), 1)
    for vehicle in analysis.vehicles:
        color = _bgr(vehicle.vehicle_type.color)
        b = vehicle.bbox
        cv2.rectangle(img, (b.x1, b.y1), (b.x2, b.y2), color, 2)
        _label(img, f"{vehicle.vehicle_type.label} {vehicle.confidence:.0%}", b.x1, b.y1, color)
    for raw in analysis.rejected:
        b = raw.bbox
        cv2.rectangle(img, (b.x1, b.y1), (b.x2, b.y2), (128, 128, 128), 1)
    plate_color = _bgr("#00B37E")
    for plate in analysis.plates:
        b = plate.bbox
        cv2.rectangle(img, (b.x1, b.y1), (b.x2, b.y2), plate_color, 2)
        text = f"{format_plate(plate.text)} {plate.confidence:.0%}"
        _label(img, text, b.x1, b.y2 + 30, plate_color)
    return img
