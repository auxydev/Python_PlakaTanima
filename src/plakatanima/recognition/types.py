"""Tanıma sonuçları için veri tipleri."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from plakatanima.core.vehicle import VehicleType


@dataclass(frozen=True, slots=True)
class BBox:
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return max(self.x2 - self.x1, 0)

    @property
    def height(self) -> int:
        return max(self.y2 - self.y1, 0)

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def center(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2

    def contains(self, x: float, y: float) -> bool:
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2

    def iou(self, other: BBox) -> float:
        ix1, iy1 = max(self.x1, other.x1), max(self.y1, other.y1)
        ix2, iy2 = min(self.x2, other.x2), min(self.y2, other.y2)
        inter = max(ix2 - ix1, 0) * max(iy2 - iy1, 0)
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0

    def offset(self, dx: int, dy: int) -> BBox:
        return BBox(self.x1 + dx, self.y1 + dy, self.x2 + dx, self.y2 + dy)

    def clip(self, width: int, height: int) -> BBox:
        return BBox(
            min(max(self.x1, 0), width),
            min(max(self.y1, 0), height),
            min(max(self.x2, 0), width),
            min(max(self.y2, 0), height),
        )

    def crop(self, frame: np.ndarray) -> np.ndarray:
        box = self.clip(frame.shape[1], frame.shape[0])
        return frame[box.y1 : box.y2, box.x1 : box.x2]

    @classmethod
    def from_xyxy(cls, values) -> BBox:
        x1, y1, x2, y2 = (round(float(v)) for v in values)
        return cls(x1, y1, x2, y2)


@dataclass(frozen=True, slots=True)
class VehicleDetection:
    bbox: BBox
    vehicle_type: VehicleType
    confidence: float
    class_name: str = ""


@dataclass(frozen=True, slots=True)
class RawPlate:
    """Plaka okuyucunun ham çıktısı (henüz normalleştirilmemiş)."""

    bbox: BBox
    text: str
    confidence: float
    detection_confidence: float = 0.0
    # OCR modelinin tahmin ettiği ülke (ör. "Turkey") ve güveni
    region: str | None = None
    region_confidence: float | None = None


@dataclass(frozen=True, slots=True)
class PlateRead:
    """Normalleştirilmiş ve araca eşlenmiş plaka okuması."""

    bbox: BBox
    text: str
    raw_text: str
    confidence: float
    vehicle: VehicleDetection | None = None
    region: str | None = None

    @property
    def vehicle_type(self) -> VehicleType:
        return self.vehicle.vehicle_type if self.vehicle else VehicleType.UNKNOWN


@dataclass(slots=True)
class FrameAnalysis:
    vehicles: list[VehicleDetection] = field(default_factory=list)
    plates: list[PlateRead] = field(default_factory=list)
    # Formata uymadığı veya güveni düşük olduğu için elenen okumalar (arayüzde gri gösterilir)
    rejected: list[RawPlate] = field(default_factory=list)
    elapsed_ms: float = 0.0
