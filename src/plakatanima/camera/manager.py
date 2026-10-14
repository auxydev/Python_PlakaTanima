"""Ayarlardaki kameraları başlatır, durdurur ve tanıma modellerini hazırlar."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from plakatanima.camera.runner import CameraCallbacks, CameraRunner, FrameAnalyzer
from plakatanima.camera.source import FrameSource, OpenCVSource
from plakatanima.config import AppConfig, CameraConfig
from plakatanima.demo.traffic import DemoAnalyzer, DemoSource, DemoTraffic, InsideList, PlateList
from plakatanima.paths import AppPaths
from plakatanima.recognition.factory import build_pipeline, build_voter

log = logging.getLogger(__name__)


def is_demo_source(source: str) -> bool:
    return source.strip().lower() == "demo"


class CameraManager:
    def __init__(
        self,
        config: AppConfig,
        paths: AppPaths,
        callbacks: CameraCallbacks,
        *,
        inside_vehicles: InsideList | None = None,
        registered_vehicles: PlateList | None = None,
    ) -> None:
        self._config = config
        self._paths = paths
        self._callbacks = callbacks
        self._runners: list[CameraRunner] = []
        # Modeller sırayla yüklensin: aynı dosyanın iki kez indirilmesini önler.
        self._build_lock = threading.Lock()
        self._traffic = DemoTraffic(inside_vehicles, registered_vehicles)

    @property
    def runners(self) -> list[CameraRunner]:
        return list(self._runners)

    def runner(self, index: int) -> CameraRunner | None:
        return next((r for r in self._runners if r.index == index), None)

    def start(self) -> None:
        self.stop()
        save = self._config.parking.save_snapshots
        for index, camera in enumerate(self._config.cameras):
            if not camera.enabled:
                continue
            runner = CameraRunner(
                index,
                camera,
                source_factory=self._source_factory(camera),
                analyzer_factory=self._analyzer_factory(camera),
                voter=build_voter(self._config.recognition),
                callbacks=self._callbacks,
                captures_dir=self._paths.captures_dir if save else None,
            )
            self._runners.append(runner)
            runner.start()
        log.info("%d kamera başlatıldı", len(self._runners))

    def stop(self) -> None:
        for runner in self._runners:
            runner.stop()
        self._runners.clear()

    def _source_factory(self, camera: CameraConfig) -> Callable[[], FrameSource]:
        if is_demo_source(camera.source):
            provider = self._traffic.provider(camera.role)
            return lambda: DemoSource(provider, on_finished=self._traffic.release)
        return lambda: OpenCVSource(camera.source)

    def _analyzer_factory(self, camera: CameraConfig) -> Callable[[], FrameAnalyzer]:
        recognition = self._config.recognition
        if is_demo_source(camera.source):
            return lambda: DemoAnalyzer(recognition)

        def build() -> FrameAnalyzer:
            with self._build_lock:
                return build_pipeline(recognition, self._paths.models_dir)

        return build
