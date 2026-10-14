from __future__ import annotations

import os
import random
import threading
import time
from datetime import datetime, timedelta

import numpy as np
import pytest

from plakatanima.camera.runner import CameraCallbacks, CameraRunner, CameraStatus
from plakatanima.camera.snapshot import cleanup_snapshots, save_snapshot
from plakatanima.camera.source import Frame, FrameSource, OpenCVSource, SourceError, describe_source
from plakatanima.cli import main
from plakatanima.config import CameraConfig, CameraRole, RecognitionConfig
from plakatanima.context import AppContext
from plakatanima.core.plate import is_valid_turkish_plate
from plakatanima.core.vehicle import VehicleType
from plakatanima.db import Database
from plakatanima.demo.seed import has_sessions, seed_demo_data
from plakatanima.demo.traffic import (
    DemoAnalyzer,
    DemoSource,
    DemoTraffic,
    DemoVehicle,
    random_plate,
)
from plakatanima.recognition.tracker import PlateVoter
from plakatanima.recognition.types import BBox, FrameAnalysis, PlateRead


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class ListSource(FrameSource):
    live = True

    def __init__(self, count=30, fail_first_open=False):
        self.count = count
        self.fail_first_open = fail_first_open
        self.opens = 0
        self.index = 0

    def open(self):
        self.opens += 1
        if self.fail_first_open and self.opens == 1:
            raise SourceError("kamera yok")

    def read(self):
        if self.index >= self.count:
            time.sleep(0.01)
            return Frame(np.zeros((48, 64, 3), np.uint8), index=self.index)
        self.index += 1
        time.sleep(0.005)
        return Frame(np.full((48, 64, 3), self.index, np.uint8), index=self.index)


class PlateAnalyzer:
    def __init__(self):
        self.calls = 0

    def analyze_frame(self, frame, roi):
        self.calls += 1
        read = PlateRead(BBox(5, 5, 30, 12), "34ABC123", "34A8C123", 0.9)
        return FrameAnalysis(plates=[read], elapsed_ms=1.0)


def make_runner(tmp_path, source, analyzer, callbacks, **camera_kwargs):
    camera = CameraConfig(name="Giriş", source="test", process_fps=50, **camera_kwargs)
    return CameraRunner(
        0,
        camera,
        source_factory=lambda: source,
        analyzer_factory=lambda: analyzer,
        voter=PlateVoter(min_hits=3, track_timeout=5, cooldown=60),
        callbacks=callbacks,
        captures_dir=tmp_path / "captures",
    )


def test_runner_confirms_plate_once_and_saves_snapshot(tmp_path):
    plates, frames, statuses = [], [], []
    callbacks = CameraCallbacks(
        on_frame=lambda i, f: frames.append(f.index),
        on_plate=lambda i, obs, confirmed: plates.append(obs),
        on_status=lambda i, status, msg: statuses.append(status),
    )
    analyzer = PlateAnalyzer()
    runner = make_runner(tmp_path, ListSource(), analyzer, callbacks, role=CameraRole.EXIT)
    runner.start()
    try:
        assert wait_for(lambda: analyzer.calls >= 6)
    finally:
        runner.stop()

    assert len(plates) == 1
    obs = plates[0]
    assert obs.plate == "34ABC123"
    assert obs.raw_text == "34A8C123"
    assert obs.role is CameraRole.EXIT
    assert obs.camera_name == "Giriş"
    assert (tmp_path / "captures" / obs.image_path).is_file()
    assert frames
    assert CameraStatus.RUNNING in statuses
    assert statuses[-1] is CameraStatus.STOPPED
    assert not runner.is_running


def test_runner_reconnects_after_open_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("plakatanima.camera.runner.MAX_RECONNECT_DELAY", 0.05)
    statuses = []
    source = ListSource(fail_first_open=True)
    callbacks = CameraCallbacks(on_status=lambda i, s, m: statuses.append(s))
    runner = make_runner(tmp_path, source, PlateAnalyzer(), callbacks)
    runner.start()
    try:
        assert wait_for(lambda: runner.status is CameraStatus.RUNNING, timeout=4)
    finally:
        runner.stop()
    assert statuses[:2] == [CameraStatus.STARTING, CameraStatus.RECONNECTING]
    assert source.opens == 2


def test_runner_reports_model_error(tmp_path):
    def broken():
        raise RuntimeError("model yok")

    camera = CameraConfig(name="X", source="test")
    runner = CameraRunner(
        0,
        camera,
        source_factory=ListSource,
        analyzer_factory=broken,
        voter=PlateVoter(),
        callbacks=CameraCallbacks(),
    )
    runner.start()
    try:
        assert wait_for(lambda: runner.status is CameraStatus.ERROR)
        assert "model yok" in runner.status_message
    finally:
        runner.stop()


def test_opencv_source_errors_and_video_file(tmp_path):
    with pytest.raises(SourceError):
        OpenCVSource(str(tmp_path / "yok.mp4")).open()

    import cv2

    path = tmp_path / "kisa.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (32, 24))
    for i in range(3):
        writer.write(np.full((24, 32, 3), i * 50, np.uint8))
    writer.release()

    source = OpenCVSource(str(path))
    assert not source.live
    source.open()
    indices = [source.read().index for _ in range(5)]  # dosya sonunda başa sarar
    source.close()
    assert indices == [1, 2, 3, 4, 5]
    assert source.fps == pytest.approx(10)


def test_describe_source_hides_credentials():
    assert describe_source("0") == "USB/Webcam #0"
    assert describe_source("demo") == "Demo (simülasyon)"
    assert describe_source("rtsp://admin:gizli@10.0.0.5:554/stream1") == "RTSP 10.0.0.5:554"
    assert describe_source("/videolar/giris.mp4") == "giris.mp4"


def test_snapshot_save_and_cleanup(tmp_path):
    image = np.zeros((40, 60, 3), np.uint8)
    when = datetime(2026, 5, 1, 13, 45, 10)
    rel = save_snapshot(
        tmp_path, image, camera_name="Çıkış Kamerası", plate="34ABC123",
        plate_bbox=BBox(5, 5, 20, 12), when=when,
    )  # fmt: skip
    assert rel == "2026-05-01/134510_cikis-kamerasi_34abc123.jpg"
    path = tmp_path / rel
    assert path.is_file()
    old = time.time() - 10 * 86400
    os.utime(path, (old, old))
    assert cleanup_snapshots(tmp_path, retention_days=5) == 1
    assert not (tmp_path / "2026-05-01").exists()


def test_random_plates_are_valid():
    rng = random.Random(1)
    assert all(is_valid_turkish_plate(random_plate(rng)) for _ in range(500))


def test_demo_source_and_analyzer_produce_plate_reads():
    vehicle = DemoVehicle("06AB1234", VehicleType.TRUCK)
    finished = []
    source = DemoSource(
        lambda: vehicle, on_finished=finished.append, size=(640, 360), frame_rate=None,
        rng=random.Random(3),
    )  # fmt: skip
    source.open()
    analyzer = DemoAnalyzer(RecognitionConfig(), ocr_error_rate=0.0)
    reads = []
    for _ in range(200):
        frame = source.read()
        analysis = analyzer.analyze_frame(frame)
        reads.extend(analysis.plates)
        if finished:
            break
    assert finished == ["06AB1234"]
    assert reads
    assert {r.text for r in reads} == {"06AB1234"}
    assert {r.vehicle_type for r in reads} == {VehicleType.TRUCK}


def test_demo_analyzer_noise_is_corrected_or_rejected():
    analyzer = DemoAnalyzer(RecognitionConfig(), ocr_error_rate=1.0, rng=random.Random(0))
    noisy = {analyzer._noisy("34ABC123") for _ in range(50)}
    assert noisy and "34ABC123" not in noisy


def test_demo_traffic_exit_uses_vehicles_inside_long_enough():
    now = datetime(2026, 1, 1, 12, 0)
    inside = [
        ("34A1111", VehicleType.CAR, now - timedelta(hours=1)),
        ("34B2222", VehicleType.BUS, now - timedelta(seconds=30)),
    ]
    traffic = DemoTraffic(lambda: inside, rng=random.Random(0), clock=lambda: now)
    exit_provider = traffic.provider(CameraRole.EXIT)
    first = exit_provider()
    assert first.plate == "34A1111"
    assert exit_provider() is None  # tek uygun araç zaten ekranda
    traffic.release("34A1111")
    assert exit_provider().plate == "34A1111"
    entry = traffic.provider(CameraRole.ENTRY)()
    assert entry.plate not in {"34A1111", "34B2222"}


def test_seed_demo_data():
    db = Database("sqlite://")
    db.create_schema()
    assert not has_sessions(db)
    now = datetime(2026, 4, 15, 15, 30)
    count = seed_demo_data(db, days=3, capacity=50, now=now, rng=random.Random(5))
    assert count > 100
    assert has_sessions(db)
    from plakatanima.config import AppConfig
    from plakatanima.services.parking import ParkingService

    stats = ParkingService(db, AppConfig(), clock=lambda: now).dashboard_stats()
    assert 0 < stats.inside <= 40
    assert stats.entries_today > 0
    assert stats.revenue_today > 0


def test_demo_context_is_isolated(tmp_path):
    ctx = AppContext.create(demo=True)
    try:
        assert ctx.demo
        assert ctx.paths.data_dir.name == "demo"
        assert [c.source for c in ctx.config.cameras] == ["demo", "demo"]
        assert has_sessions(ctx.db)
    finally:
        ctx.close()
    real = AppContext.create()
    try:
        assert not has_sessions(real.db)
    finally:
        real.close()


def test_cli_run_demo_starts_and_stops(capsys):
    started = time.monotonic()
    assert main(["run", "--demo", "--duration", "1.5"]) == 0
    assert time.monotonic() - started < 15
    out = capsys.readouterr().out
    assert "Giriş Kamerası" in out
    assert "Durduruldu" in out
    assert not [t for t in threading.enumerate() if t.name.startswith("cam")]
