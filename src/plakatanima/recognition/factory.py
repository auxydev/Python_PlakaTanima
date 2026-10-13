"""Ayarlara göre tanıma bileşenlerini oluşturur."""

from __future__ import annotations

import logging
from pathlib import Path

from plakatanima.config import RecognitionConfig
from plakatanima.recognition.model_store import ProgressCallback, resolve_yolox_model
from plakatanima.recognition.pipeline import RecognitionPipeline
from plakatanima.recognition.plate_reader import FastAlprPlateReader, PlateReader
from plakatanima.recognition.tracker import PlateVoter
from plakatanima.recognition.vehicle_detector import (
    NullVehicleDetector,
    UltralyticsVehicleDetector,
    VehicleDetector,
    YoloxVehicleDetector,
)

log = logging.getLogger(__name__)


def build_vehicle_detector(
    config: RecognitionConfig,
    models_dir: Path,
    progress: ProgressCallback | None = None,
) -> VehicleDetector:
    if config.vehicle_detector == "none":
        return NullVehicleDetector()
    if config.vehicle_detector == "ultralytics":
        return UltralyticsVehicleDetector(
            config.vehicle_model, confidence=config.vehicle_confidence, device=config.device
        )
    model_path = resolve_yolox_model(config.vehicle_model, models_dir, progress)
    log.info("Araç modeli: %s", model_path.name)
    return YoloxVehicleDetector(
        model_path, confidence=config.vehicle_confidence, device=config.device
    )


def build_plate_reader(config: RecognitionConfig) -> PlateReader:
    log.info("Plaka modelleri: %s + %s", config.plate_detector_model, config.ocr_model)
    return FastAlprPlateReader(
        detector_model=config.plate_detector_model,
        ocr_model=config.ocr_model,
        detector_confidence=config.plate_detector_confidence,
        device=config.device,
    )


def build_pipeline(
    config: RecognitionConfig,
    models_dir: Path,
    progress: ProgressCallback | None = None,
) -> RecognitionPipeline:
    return RecognitionPipeline(
        build_vehicle_detector(config, models_dir, progress),
        build_plate_reader(config),
        config,
    )


def build_voter(config: RecognitionConfig) -> PlateVoter:
    return PlateVoter(
        min_hits=config.min_hits,
        track_timeout=config.track_timeout_seconds,
        cooldown=config.cooldown_seconds,
    )
