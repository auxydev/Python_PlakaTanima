from __future__ import annotations

import math

import numpy as np
import pytest

from plakatanima.config import RecognitionConfig
from plakatanima.core.vehicle import VehicleType
from plakatanima.recognition.model_store import ModelError, download_file, resolve_yolox_model
from plakatanima.recognition.pipeline import (
    RecognitionPipeline,
    annotate,
    match_vehicle,
    normalize_raw_plate,
)
from plakatanima.recognition.plate_reader import PlateReader, ocr_confidence
from plakatanima.recognition.types import BBox, RawPlate, VehicleDetection
from plakatanima.recognition.vehicle_detector import (
    VehicleDetector,
    YoloxVehicleDetector,
    nms,
)


class FakeDetector(VehicleDetector):
    def __init__(self, detections):
        self.detections = detections
        self.frames = []

    def detect(self, frame):
        self.frames.append(frame.shape)
        return list(self.detections)


class FakeReader(PlateReader):
    def __init__(self, plates):
        self.plates = plates

    def read(self, frame):
        return list(self.plates)


def test_bbox_geometry():
    a, b = BBox(0, 0, 10, 10), BBox(5, 5, 15, 15)
    assert a.area == 100
    assert a.iou(b) == pytest.approx(25 / 175)
    assert a.contains(*a.center)
    assert a.offset(3, 4) == BBox(3, 4, 13, 14)
    assert BBox(-5, -5, 50, 50).clip(20, 30) == BBox(0, 0, 20, 30)


def test_nms_is_class_agnostic():
    boxes = np.array([[0, 0, 10, 10], [1, 1, 10, 10], [20, 20, 30, 30]], dtype=np.float32)
    scores = np.array([0.6, 0.9, 0.5], dtype=np.float32)
    assert nms(boxes, scores, 0.45) == [1, 2]
    assert nms(np.zeros((0, 4)), np.zeros(0), 0.5) == []


def test_match_vehicle_prefers_smallest_containing_box():
    big = VehicleDetection(BBox(0, 0, 1000, 1000), VehicleType.TRUCK, 0.6)
    small = VehicleDetection(BBox(100, 100, 400, 400), VehicleType.CAR, 0.9)
    assert match_vehicle(BBox(200, 300, 260, 320), [big, small]) is small
    assert match_vehicle(BBox(600, 600, 660, 620), [big, small]) is big
    assert match_vehicle(BBox(2000, 0, 2100, 20), [big, small]) is None


def test_ocr_confidence_uses_text_slots_only():
    assert ocr_confidence("34AB", [1.0, 0.5, 1.0, 0.5, 0.0, 0.0]) == pytest.approx(0.75)
    assert ocr_confidence("X", 0.42) == pytest.approx(0.42)
    assert ocr_confidence("", []) == 0.0


def test_foreign_region_disables_turkish_corrections():
    czech = RawPlate(BBox(0, 0, 1, 1), "5AU5341", 1.0, region="Czech Republic",
                     region_confidence=0.99)  # fmt: skip
    assert normalize_raw_plate(czech, turkish_only=True) is None
    assert normalize_raw_plate(czech, turkish_only=False) == "5AU5341"
    unsure = RawPlate(BBox(0, 0, 1, 1), "34A8C123", 1.0, region="Greece", region_confidence=0.3)
    assert normalize_raw_plate(unsure, turkish_only=True) == "34ABC123"
    turkish = RawPlate(BBox(0, 0, 1, 1), "34A8C123", 1.0, region="Turkey", region_confidence=1)
    assert normalize_raw_plate(turkish, turkish_only=True) == "34ABC123"


def test_pipeline_normalizes_filters_and_matches():
    config = RecognitionConfig(min_ocr_confidence=0.6)
    car = VehicleDetection(BBox(50, 50, 450, 400), VehicleType.CAR, 0.9)
    reader = FakeReader(
        [
            RawPlate(BBox(200, 330, 300, 360), "34 A8C 123", 0.9),
            RawPlate(BBox(10, 10, 60, 25), "HELLO", 0.95),  # format dışı
            RawPlate(BBox(500, 330, 600, 360), "06AB1234", 0.3),  # düşük güven
        ]
    )
    pipeline = RecognitionPipeline(FakeDetector([car]), reader, config)
    analysis = pipeline.analyze(np.zeros((480, 640, 3), np.uint8))
    assert [p.text for p in analysis.plates] == ["34ABC123"]
    assert analysis.plates[0].raw_text == "34 A8C 123"
    assert analysis.plates[0].vehicle_type is VehicleType.CAR
    assert [r.text for r in analysis.rejected] == ["HELLO", "06AB1234"]

    # Ayar değişikliği yeniden oluşturmadan uygulanır.
    config.turkish_plates_only = False
    analysis = pipeline.analyze(np.zeros((480, 640, 3), np.uint8))
    assert [p.text for p in analysis.plates] == ["34ABC123", "HELLO"]
    assert analysis.elapsed_ms >= 0


def test_pipeline_roi_crops_and_offsets_boxes():
    detector = FakeDetector([VehicleDetection(BBox(0, 0, 100, 100), VehicleType.BUS, 0.8)])
    reader = FakeReader([RawPlate(BBox(10, 10, 60, 25), "06AB1234", 0.9)])
    pipeline = RecognitionPipeline(detector, reader, RecognitionConfig())
    frame = np.zeros((200, 400, 3), np.uint8)
    analysis = pipeline.analyze(frame, roi=(0.5, 0.5, 1.0, 1.0))
    assert detector.frames == [(100, 200, 3)]
    assert analysis.vehicles[0].bbox == BBox(200, 100, 300, 200)
    assert analysis.plates[0].bbox == BBox(210, 110, 260, 125)
    assert analysis.plates[0].vehicle_type is VehicleType.BUS
    annotated = annotate(frame, analysis, roi=(0.5, 0.5, 1.0, 1.0))
    assert annotated.shape == frame.shape
    assert annotated.any() and not frame.any()


class FakeSession:
    def __init__(self, output):
        self.output = output
        self.inputs = []

    def run(self, _names, feeds):
        self.inputs.append(next(iter(feeds.values())))
        return [self.output]


def _yolox_with_output(output, input_size=(64, 64)):
    detector = object.__new__(YoloxVehicleDetector)
    detector._session = FakeSession(output)
    detector._input_name = "images"
    detector._input_size = input_size
    detector._grids, detector._strides = YoloxVehicleDetector._make_grids(*input_size)
    detector.confidence = 0.3
    detector.nms_iou = 0.45
    return detector


def test_yolox_decoding_and_agnostic_nms():
    anchors = (64 // 8) ** 2 + (64 // 16) ** 2 + (64 // 32) ** 2
    raw = np.zeros((1, anchors, 85), np.float32)
    # stride 8 ızgarasında (x=2, y=3) hücresi: merkez (20, 28), boyut 16x16
    idx = 3 * 8 + 2
    raw[0, idx, :4] = [0.5, 0.5, math.log(2), math.log(2)]
    raw[0, idx, 4] = 0.9
    raw[0, idx, 5 + 2] = 0.8  # car
    raw[0, idx, 5 + 7] = 0.5  # truck (aynı kutu, daha düşük skor)
    detector = _yolox_with_output(raw)

    frame = np.zeros((128, 128, 3), np.uint8)  # ölçek oranı 0.5
    detections = detector.detect(frame)
    assert len(detections) == 1
    det = detections[0]
    assert det.vehicle_type is VehicleType.CAR
    assert det.class_name == "car"
    assert det.confidence == pytest.approx(0.72)
    assert det.bbox == BBox(24, 40, 56, 72)
    blob = detector._session.inputs[0]
    assert blob.shape == (1, 3, 64, 64)
    assert blob.dtype == np.float32


def test_yolox_returns_empty_below_threshold():
    raw = np.zeros((1, 84, 85), np.float32)
    assert _yolox_with_output(raw).detect(np.zeros((64, 64, 3), np.uint8)) == []


def test_resolve_model_errors(tmp_path):
    with pytest.raises(ModelError, match="Bilinmeyen"):
        resolve_yolox_model("yolox_xxl", tmp_path)
    with pytest.raises(ModelError, match="bulunamadı"):
        resolve_yolox_model(str(tmp_path / "yok.onnx"), tmp_path)
    custom = tmp_path / "ozel.onnx"
    custom.write_bytes(b"x")
    assert resolve_yolox_model(str(custom), tmp_path) == custom


def test_download_verifies_checksum(tmp_path):
    source = tmp_path / "kaynak.bin"
    source.write_bytes(b"model verisi")
    target = tmp_path / "models" / "model.onnx"
    with pytest.raises(ModelError, match="doğrulaması"):
        download_file(source.as_uri(), target, sha256="0" * 64)
    assert not target.exists()
    assert not target.with_name("model.onnx.part").exists()

    import hashlib

    progress = []
    digest = hashlib.sha256(b"model verisi").hexdigest()
    download_file(source.as_uri(), target, sha256=digest, progress=lambda d, t: progress.append(d))
    assert target.read_bytes() == b"model verisi"
    assert progress[-1] == len(b"model verisi")
