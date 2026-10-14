"""Demo modu: kamera ve model olmadan otopark trafiği simülasyonu.

* :class:`DemoSource` kameraya yaklaşan, bekleyen ve uzaklaşan araçlar çizer;
  her karede gerçek plaka/araç bilgisini ``frame.meta["truth"]`` içinde taşır.
* :class:`DemoAnalyzer` bu bilgiyi tanıma sonucu gibi döndürür; gerçekçilik için
  ara sıra OCR hatası (ör. B -> 8) ve değişken güven değerleri ekler. Hatalı
  okumalar gerçek sistemdeki gibi oylama ve format düzeltmesiyle ayıklanır.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from plakatanima.camera.source import Frame, FrameSource
from plakatanima.config import CameraRole, RecognitionConfig
from plakatanima.core.plate import PROVINCES
from plakatanima.core.vehicle import VehicleType
from plakatanima.demo.scene import background, render_vehicle
from plakatanima.recognition.pipeline import normalize_raw_plate
from plakatanima.recognition.types import (
    BBox,
    FrameAnalysis,
    PlateRead,
    RawPlate,
    VehicleDetection,
)

# Sık görülen il kodları daha olası olsun
_COMMON_PROVINCES = ["34"] * 8 + ["06"] * 4 + ["35"] * 3 + ["16", "07", "01", "41", "42"]
_LETTERS = "ABCDEFGHIJKLMNOPRSTUVYZ"
_VEHICLE_WEIGHTS = {
    VehicleType.CAR: 62,
    VehicleType.LIGHT_COMMERCIAL: 15,
    VehicleType.MOTORCYCLE: 10,
    VehicleType.TRUCK: 7,
    VehicleType.BUS: 6,
}
_COLORS = [(40, 40, 160), (160, 60, 40), (210, 210, 210), (35, 35, 35), (40, 120, 200),
           (60, 140, 60), (120, 120, 120), (30, 90, 160), (200, 200, 230)]  # fmt: skip
_OCR_CONFUSIONS = {"B": "8", "8": "B", "0": "O", "O": "0", "1": "I", "I": "1", "S": "5",
                   "5": "S", "Z": "2", "2": "Z", "G": "6", "6": "G"}  # fmt: skip


def random_plate(rng: random.Random) -> str:
    province = rng.choice(_COMMON_PROVINCES + list(PROVINCES))
    n_letters = rng.choice((1, 2, 2, 3, 3))
    letters = "".join(rng.choice(_LETTERS) for _ in range(n_letters))
    n_digits = {1: rng.choice((4, 5)), 2: rng.choice((3, 4)), 3: rng.choice((2, 3))}[n_letters]
    digits = str(rng.randint(10 ** (n_digits - 1), 10**n_digits - 1))
    return f"{province}{letters}{digits}"


def random_vehicle_type(rng: random.Random) -> VehicleType:
    types, weights = zip(*_VEHICLE_WEIGHTS.items(), strict=True)
    return rng.choices(types, weights)[0]


@dataclass(frozen=True, slots=True)
class DemoVehicle:
    plate: str
    vehicle_type: VehicleType
    color: tuple[int, int, int] = (160, 60, 40)


@dataclass(frozen=True, slots=True)
class DemoTruth:
    vehicle: DemoVehicle
    vehicle_box: BBox
    plate_box: BBox
    plate_visible: bool


VehicleProvider = Callable[[], DemoVehicle | None]
PlateList = Callable[[], list[tuple[str, VehicleType]]]
# İçerideki araçlar: (plaka, tip, giriş zamanı)
InsideList = Callable[[], list[tuple[str, VehicleType, datetime]]]

# Çıkış kamerası yalnızca en az bu kadar süredir içeride olan araçları gösterir.
MIN_DEMO_STAY = timedelta(minutes=3)


class DemoTraffic:
    """Kamera görevine göre sıradaki demo aracını seçer.

    Giriş kameraları yeni (bazen kayıtlı) araçlar, çıkış kameraları ise
    içerideki araçlardan birini gösterir.
    """

    def __init__(
        self,
        inside: InsideList | None = None,
        registered: PlateList | None = None,
        rng: random.Random | None = None,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._inside = inside or (lambda: [])
        self._registered = registered or (lambda: [])
        self._rng = rng or random.Random()
        self._clock = clock
        self._lock = threading.Lock()
        # Kamerada şu an gösterilen araçlar (iki kamera aynı aracı göstermesin)
        self._on_screen: set[str] = set()

    def provider(self, role: CameraRole) -> VehicleProvider:
        def next_vehicle() -> DemoVehicle | None:
            with self._lock:
                exit_ = role is CameraRole.EXIT or (
                    role is CameraRole.BOTH and self._rng.random() < 0.5
                )
                choice = self._pick_exit() if exit_ else self._pick_entry()
                if choice is None:
                    return None
                return DemoVehicle(choice[0], choice[1], self._rng.choice(_COLORS))

        return next_vehicle

    def release(self, plate: str) -> None:
        with self._lock:
            self._on_screen.discard(plate)

    def _pick_exit(self) -> tuple[str, VehicleType] | None:
        latest_entry = self._clock() - MIN_DEMO_STAY
        candidates = [
            (plate, vtype)
            for plate, vtype, entered in self._inside()
            if plate not in self._on_screen and entered <= latest_entry
        ]
        if not candidates:
            return None
        choice = self._rng.choice(candidates)
        self._on_screen.add(choice[0])
        return choice

    def _pick_entry(self) -> tuple[str, VehicleType]:
        inside = {plate for plate, _, _ in self._inside()} | self._on_screen
        registered = [c for c in self._registered() if c[0] not in inside]
        if registered and self._rng.random() < 0.25:
            plate, vtype = self._rng.choice(registered)
            if vtype is VehicleType.UNKNOWN:
                vtype = random_vehicle_type(self._rng)
        else:
            plate, vtype = random_plate(self._rng), random_vehicle_type(self._rng)
        self._on_screen.add(plate)
        return plate, vtype


class DemoSource(FrameSource):
    """Araçların kameraya yaklaşıp geçtiği yapay görüntü akışı."""

    live = True

    def __init__(
        self,
        provider: VehicleProvider,
        *,
        on_finished: Callable[[str], None] | None = None,
        size: tuple[int, int] = (1280, 720),
        frame_rate: float | None = 15.0,
        rng: random.Random | None = None,
    ) -> None:
        self._provider = provider
        self._on_finished = on_finished or (lambda _plate: None)
        self._size = size
        self._frame_rate = frame_rate
        self._rng = rng or random.Random()
        self._background = background(*size)
        self._index = 0
        self._vehicle: DemoVehicle | None = None
        self._phase_frames: list[tuple[float, float]] = []  # (ölçek, alt kenar) dizisi
        self._idle = 0
        self._next_time = 0.0

    @property
    def fps(self) -> float | None:
        return self._frame_rate

    def open(self) -> None:
        self._next_time = time.monotonic()
        self._idle = self._frames(1.0)

    def _frames(self, seconds: float) -> int:
        return max(int(seconds * (self._frame_rate or 15.0)), 1)

    def _start_vehicle(self) -> None:
        self._vehicle = self._provider()
        if self._vehicle is None:
            self._idle = self._frames(2.0)
            return
        approach = self._frames(self._rng.uniform(2.0, 3.0))
        hold = self._frames(self._rng.uniform(1.5, 2.5))
        leave = self._frames(0.8)
        frames = [(0.45 + 0.55 * i / approach, 0.62 + 0.33 * i / approach) for i in range(approach)]
        frames += [(1.0, 0.95)] * hold
        frames += [(1.0 + 0.6 * i / leave, 0.95 + 0.3 * i / leave) for i in range(leave)]
        self._phase_frames = frames

    def read(self) -> Frame | None:
        if self._frame_rate:
            self._next_time += 1.0 / self._frame_rate
            delay = self._next_time - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                self._next_time = time.monotonic()

        image = self._background.copy()
        meta: dict = {}
        if self._vehicle is None and self._idle > 0:
            self._idle -= 1
        elif self._vehicle is None:
            self._start_vehicle()

        if self._vehicle is not None and self._phase_frames:
            scale, bottom = self._phase_frames.pop(0)
            vehicle_box, plate_box = render_vehicle(
                image,
                self._vehicle.plate,
                self._vehicle.vehicle_type,
                scale=scale,
                bottom_y=bottom,
                color=self._vehicle.color,
            )
            meta["truth"] = DemoTruth(
                vehicle=self._vehicle,
                vehicle_box=BBox(*vehicle_box),
                plate_box=BBox(*plate_box),
                plate_visible=scale >= 0.7 and plate_box[3] <= self._size[1],
            )
            if not self._phase_frames:
                self._on_finished(self._vehicle.plate)
                self._vehicle = None
                self._idle = self._frames(self._rng.uniform(1.0, 4.0))

        self._index += 1
        return Frame(image=image, index=self._index, meta=meta)


class DemoAnalyzer:
    """Gerçek modeller yerine demo kaynağının bilgisini kullanan tanıma."""

    def __init__(
        self,
        config: RecognitionConfig,
        *,
        ocr_error_rate: float = 0.15,
        rng: random.Random | None = None,
    ) -> None:
        self.config = config
        self.ocr_error_rate = ocr_error_rate
        self._rng = rng or random.Random()

    def analyze_frame(self, frame: Frame, roi=None) -> FrameAnalysis:
        started = time.perf_counter()
        truth: DemoTruth | None = frame.meta.get("truth")
        analysis = FrameAnalysis()
        if truth is not None:
            vehicle = VehicleDetection(
                bbox=truth.vehicle_box,
                vehicle_type=truth.vehicle.vehicle_type,
                confidence=round(self._rng.uniform(0.72, 0.97), 3),
                class_name=truth.vehicle.vehicle_type.value,
            )
            analysis.vehicles.append(vehicle)
            if truth.plate_visible:
                raw = RawPlate(
                    bbox=truth.plate_box,
                    text=self._noisy(truth.vehicle.plate),
                    confidence=round(self._rng.uniform(0.82, 0.995), 3),
                    detection_confidence=0.9,
                    region="Turkey",
                    region_confidence=0.95,
                )
                text = normalize_raw_plate(raw, turkish_only=self.config.turkish_plates_only)
                if text is None:
                    analysis.rejected.append(raw)
                else:
                    analysis.plates.append(
                        PlateRead(raw.bbox, text, raw.text, raw.confidence, vehicle, raw.region)
                    )
        analysis.elapsed_ms = (time.perf_counter() - started) * 1000
        return analysis

    def _noisy(self, plate: str) -> str:
        if self._rng.random() >= self.ocr_error_rate:
            return plate
        positions = [i for i, ch in enumerate(plate) if ch in _OCR_CONFUSIONS]
        if not positions:
            return plate
        i = self._rng.choice(positions)
        return plate[:i] + _OCR_CONFUSIONS[plate[i]] + plate[i + 1 :]
