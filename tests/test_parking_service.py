from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from plakatanima.config import AppConfig, CameraRole
from plakatanima.core.vehicle import VehicleType
from plakatanima.db import (
    Database,
    EventAction,
    ParkingSession,
    PaymentMethod,
    SessionStatus,
)
from plakatanima.services.parking import ParkingService, PlateObservation
from plakatanima.services.registry import TariffService, VehicleData, VehicleRegistry


class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture
def db():
    database = Database("sqlite://")
    database.create_schema()
    yield database
    database.dispose()


@pytest.fixture
def clock():
    return Clock(datetime(2026, 3, 2, 9, 0, 0))


@pytest.fixture
def config():
    cfg = AppConfig()
    cfg.parking.capacity = 3
    cfg.parking.min_stay_seconds = 120
    return cfg


@pytest.fixture
def service(db, config, clock):
    return ParkingService(db, config, clock=clock)


def obs(plate="34ABC123", role=CameraRole.ENTRY, **kwargs) -> PlateObservation:
    camera = {CameraRole.ENTRY: "Giriş", CameraRole.EXIT: "Çıkış"}.get(role, "Kapı")
    return PlateObservation(plate=plate, camera_name=camera, role=role, **kwargs)


def test_entry_then_exit_charges_tariff(service, clock):
    entry = service.process(obs(vehicle_type=VehicleType.CAR, confidence=0.93))
    assert entry.action is EventAction.ENTRY
    assert entry.session_id is not None
    assert "34 ABC 123" in entry.message

    clock.advance(hours=2, minutes=10)
    exit_ = service.process(obs(role=CameraRole.EXIT))
    assert exit_.action is EventAction.EXIT
    assert exit_.session_id == entry.session_id
    assert exit_.fee == Decimal("120.00")  # 60 + 2 * 30
    assert exit_.duration == timedelta(hours=2, minutes=10)
    assert exit_.needs_payment
    assert service.inside_count() == 0


def test_short_stay_is_free_and_marked_paid(service, clock):
    service.process(obs())
    clock.advance(minutes=10)
    result = service.process(obs(role=CameraRole.EXIT))
    assert result.fee == Decimal("0.00")
    assert result.is_paid
    assert not result.needs_payment


def test_repeated_entry_reads_are_ignored(service, clock):
    first = service.process(obs())
    clock.advance(seconds=30)
    second = service.process(obs())
    assert second.action is EventAction.DUPLICATE
    assert second.session_id == first.session_id
    assert service.inside_count() == 1


def test_stale_open_session_is_closed_on_new_entry(service, clock, db):
    first = service.process(obs())
    clock.advance(hours=5)
    second = service.process(obs())
    assert second.action is EventAction.ENTRY
    assert second.session_id != first.session_id
    with db.session() as s:
        old = s.get(ParkingSession, first.session_id)
        assert old.status is SessionStatus.EXIT_MISSED
        assert old.exit_time == clock.now
    assert service.inside_count() == 1


def test_exit_without_entry(service, clock):
    result = service.process(obs(role=CameraRole.EXIT))
    assert result.action is EventAction.UNMATCHED_EXIT
    assert result.session_id is None
    assert result.is_alert


def test_repeated_exit_read_is_duplicate(service, clock):
    service.process(obs())
    clock.advance(hours=1)
    service.process(obs(role=CameraRole.EXIT))
    clock.advance(seconds=20)
    assert service.process(obs(role=CameraRole.EXIT)).action is EventAction.DUPLICATE
    clock.advance(minutes=10)
    assert service.process(obs(role=CameraRole.EXIT)).action is EventAction.UNMATCHED_EXIT


def test_single_camera_both_directions(service, clock):
    both = CameraRole.BOTH
    assert service.process(obs(role=both)).action is EventAction.ENTRY
    clock.advance(seconds=60)
    assert service.process(obs(role=both)).action is EventAction.DUPLICATE
    clock.advance(minutes=45)
    assert service.process(obs(role=both)).action is EventAction.EXIT
    clock.advance(seconds=30)
    assert service.process(obs(role=both)).action is EventAction.DUPLICATE
    clock.advance(minutes=5)
    assert service.process(obs(role=both)).action is EventAction.ENTRY


def test_manual_operations(service, clock):
    manual_entry = obs("06AB1234", manual=True)
    assert service.process(manual_entry).action is EventAction.ENTRY
    assert service.process(manual_entry).action is EventAction.DUPLICATE
    assert "zaten içeride" in service.process(manual_entry).message
    clock.advance(minutes=1)
    exit_ = service.process(obs("06AB1234", role=CameraRole.EXIT, manual=True))
    assert exit_.action is EventAction.EXIT
    no_entry = service.process(obs("35A1234", role=CameraRole.EXIT, manual=True))
    assert no_entry.action is EventAction.UNMATCHED_EXIT


def test_subscriber_and_blacklist(service, db, clock):
    registry = VehicleRegistry(db)
    registry.save(
        VehicleData(
            plate="34 SUB 01",
            vehicle_type=VehicleType.LIGHT_COMMERCIAL,
            owner_name="Ayşe",
            is_subscriber=True,
            subscription_end=date(2026, 12, 31),
        )
    )
    registry.save(VehicleData(plate="34BAD99", is_blacklisted=True, blacklist_reason="borç"))

    entry = service.process(obs("34SUB01", vehicle_type=VehicleType.CAR))
    # Kayıtlı aracın tipi tespit edilen tipe göre önceliklidir.
    assert entry.vehicle_type is VehicleType.LIGHT_COMMERCIAL
    assert entry.is_subscriber
    assert entry.owner_name == "Ayşe"
    clock.advance(hours=6)
    exit_ = service.process(obs("34SUB01", role=CameraRole.EXIT))
    assert exit_.fee == Decimal("0.00")
    assert exit_.is_paid
    assert "abone" in exit_.message

    bad = service.process(obs("34BAD99"))
    assert bad.is_blacklisted
    assert bad.is_alert
    assert "KARA LİSTE (borç)" in bad.message


def test_expired_subscription_pays(service, db, clock):
    VehicleRegistry(db).save(
        VehicleData(plate="34OLD01", is_subscriber=True, subscription_end=date(2026, 1, 1))
    )
    service.process(obs("34OLD01"))
    clock.advance(hours=1)
    assert service.process(obs("34OLD01", role=CameraRole.EXIT)).fee == Decimal("60.00")


def test_exit_fills_unknown_vehicle_type_and_uses_its_tariff(service, clock):
    service.process(obs("34TR001"))
    clock.advance(hours=1)
    result = service.process(obs("34TR001", role=CameraRole.EXIT, vehicle_type=VehicleType.TRUCK))
    assert result.vehicle_type is VehicleType.TRUCK
    assert result.fee == Decimal("150.00")


def test_lot_full_warning(service, clock):
    for plate in ("34A1111", "34A2222", "34A3333"):
        assert not service.process(obs(plate)).lot_full
    assert service.process(obs("34A4444")).lot_full


def test_payment_and_dashboard_stats(service, clock):
    service.process(obs("34A1111", vehicle_type=VehicleType.CAR))
    service.process(obs("34A2222", vehicle_type=VehicleType.MOTORCYCLE))
    clock.advance(hours=1, minutes=30)
    paid = service.process(obs("34A1111", role=CameraRole.EXIT))
    assert paid.fee == Decimal("90.00")

    stats = service.dashboard_stats()
    assert stats.inside == 1
    assert stats.entries_today == 2
    assert stats.exits_today == 1
    assert stats.unpaid_count == 1
    assert stats.revenue_today == Decimal("0.00")
    assert stats.inside_by_type == {VehicleType.MOTORCYCLE: 1}

    service.record_payment(paid.session_id, PaymentMethod.CARD, amount=Decimal("80"))
    stats = service.dashboard_stats()
    assert stats.revenue_today == Decimal("80.00")
    assert stats.unpaid_count == 0
    assert stats.free_spaces == 2


def test_current_fee_for_vehicle_inside(service, clock):
    entry = service.process(obs())
    clock.advance(hours=3)
    assert service.current_fee(entry.session_id) == Decimal("120.00")


def test_tariff_update_changes_fee(service, db, clock):
    TariffService(db).update(
        VehicleType.CAR,
        free_minutes=0,
        first_hour_fee=Decimal("100"),
        additional_hour_fee=Decimal("50"),
        daily_max_fee=Decimal("0"),
    )
    service.process(obs(vehicle_type=VehicleType.CAR))
    clock.advance(hours=2)
    assert service.process(obs(role=CameraRole.EXIT)).fee == Decimal("150.00")


def test_events_are_logged(service, clock):
    service.process(obs(raw_text="34A8C123", confidence=0.8))
    service.process(obs())
    events = service.recent_events()
    assert [e.action for e in events] == [EventAction.DUPLICATE, EventAction.ENTRY]
    assert events[1].raw_text == "34A8C123"


def test_find_sessions_filters(service, clock):
    service.process(obs("34A1111", vehicle_type=VehicleType.CAR))
    service.process(obs("06B2222", vehicle_type=VehicleType.BUS))
    assert len(service.find_sessions()) == 2
    assert [s.plate for s in service.find_sessions(plate="06 b")] == ["06B2222"]
    assert len(service.find_sessions(vehicle_type=VehicleType.BUS)) == 1
    tomorrow = clock.now + timedelta(days=1)
    assert service.find_sessions(start=tomorrow) == []


def test_only_one_open_session_per_plate_at_db_level(db):
    with pytest.raises(IntegrityError), db.session() as s:
        s.add(ParkingSession(plate="34X1234", status=SessionStatus.OPEN))
        s.add(ParkingSession(plate="34X1234", status=SessionStatus.OPEN))
        s.flush()


def test_registry_crud(db):
    registry = VehicleRegistry(db)
    vehicle = registry.save(VehicleData(plate="34 abc 123", owner_name="Mehmet"))
    assert vehicle.plate == "34ABC123"
    with pytest.raises(ValueError):
        registry.save(VehicleData(plate="34ABC123"))
    registry.save(
        VehicleData(plate="34ABC123", owner_name="Mehmet Y.", phone="555"), vehicle_id=vehicle.id
    )
    assert registry.get("34 ABC 123").owner_name == "Mehmet Y."
    assert [v.plate for v in registry.search("mehmet")] == ["34ABC123"]
    assert registry.search(blacklisted_only=True) == []
    data = VehicleData.from_vehicle(registry.get("34ABC123"))
    assert data.phone == "555"
    registry.delete(vehicle.id)
    assert registry.get("34ABC123") is None
