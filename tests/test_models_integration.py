"""Gerçek modellerle uçtan uca testler.

Model indirdikleri ve yavaş oldukları için varsayılan olarak atlanır:

    PLAKATANIMA_MODEL_TESTS=1 pytest tests/test_models_integration.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from plakatanima.config import RecognitionConfig
from plakatanima.core.vehicle import VehicleType
from plakatanima.demo.scene import background, render_vehicle
from plakatanima.recognition.factory import build_pipeline, build_plate_reader

pytestmark = pytest.mark.skipif(
    os.environ.get("PLAKATANIMA_MODEL_TESTS") != "1",
    reason="PLAKATANIMA_MODEL_TESTS=1 ile çalıştırın (model indirir)",
)


@pytest.mark.parametrize("plate", ["34ABC123", "06BK4521", "35A12345"])
def test_reads_synthetic_turkish_plate(plate):
    frame = background(1280, 720)
    render_vehicle(frame, plate, VehicleType.CAR)
    reader = build_plate_reader(RecognitionConfig())
    texts = [p.text for p in reader.read(frame)]
    assert plate in texts


def test_full_pipeline_with_yolox(tmp_path):
    models_dir = Path(os.environ.get("PLAKATANIMA_MODELS_DIR", tmp_path))
    config = RecognitionConfig(vehicle_model="yolox_nano")
    pipeline = build_pipeline(config, models_dir)
    frame = background(1280, 720)
    render_vehicle(frame, "34ABC123", VehicleType.TRUCK)
    analysis = pipeline.analyze(frame)
    assert [p.text for p in analysis.plates] == ["34ABC123"]
