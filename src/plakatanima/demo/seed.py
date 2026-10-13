"""Demo veritabanını geçmiş kayıtlarla doldurur (grafikler ve raporlar boş görünmesin)."""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from plakatanima.core.plate import format_plate
from plakatanima.core.vehicle import VehicleType
from plakatanima.db.database import Database
from plakatanima.db.models import (
    DetectionEvent,
    EventAction,
    ParkingSession,
    PaymentMethod,
    SessionStatus,
    Tariff,
    Vehicle,
)
from plakatanima.demo.traffic import random_plate, random_vehicle_type

_DEMO_VEHICLES = [
    ("34ABC123", VehicleType.CAR, "Ayşe Yılmaz", True, False, ""),
    ("06KLM456", VehicleType.LIGHT_COMMERCIAL, "Mehmet Kaya", True, False, ""),
    ("35TR2024", VehicleType.CAR, "Zeynep Demir", True, False, ""),
    ("16MTR77", VehicleType.MOTORCYCLE, "Can Öztürk", True, False, ""),
    ("34XYZ999", VehicleType.CAR, "", False, True, "Ödenmemiş borç"),
    ("41BK1453", VehicleType.TRUCK, "", False, True, "Çalıntı ihbarı"),
    ("07ANT07", VehicleType.BUS, "Akdeniz Turizm", False, False, ""),
]

# Saatlere göre giriş yoğunluğu (sabah ve akşam tepe noktaları)
_HOURLY_WEIGHTS = [1, 1, 1, 1, 1, 2, 4, 9, 14, 12, 8, 7, 8, 8, 7, 7, 9, 12, 13, 10, 7, 5, 3, 2]
_ENTRY_CAMERA = "Giriş Kamerası"
_EXIT_CAMERA = "Çıkış Kamerası"


def has_sessions(db: Database) -> bool:
    with db.session() as s:
        return bool(s.scalar(select(func.count()).select_from(ParkingSession)))


def seed_demo_data(
    db: Database,
    *,
    days: int = 21,
    capacity: int = 100,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> int:
    """Son ``days`` gün için kayıt üretir; eklenen park kaydı sayısını döndürür."""
    rng = rng or random.Random(2026)
    now = (now or datetime.now()).replace(microsecond=0)
    count = 0
    with db.session() as s:
        tariffs = {t.vehicle_type: t.to_rule() for t in s.scalars(select(Tariff))}
        registry: dict[str, Vehicle] = {}
        for plate, vtype, owner, subscriber, blacklisted, reason in _DEMO_VEHICLES:
            vehicle = s.scalar(select(Vehicle).where(Vehicle.plate == plate))
            if vehicle is None:
                vehicle = Vehicle(
                    plate=plate,
                    vehicle_type=vtype,
                    owner_name=owner,
                    phone=f"05{rng.randint(30, 59)} {rng.randint(100, 999)} {rng.randint(10, 99)}"
                    f" {rng.randint(10, 99)}",
                    is_subscriber=subscriber,
                    subscription_end=date(now.year, 12, 31) if subscriber else None,
                    is_blacklisted=blacklisted,
                    blacklist_reason=reason,
                )
                s.add(vehicle)
            registry[plate] = vehicle
        s.flush()

        open_plates: set[str] = set()
        for day_offset in range(days, -1, -1):
            day = now.date() - timedelta(days=day_offset)
            weekend = day.weekday() >= 5
            entries = rng.randint(45, 80) if weekend else rng.randint(80, 140)
            for _ in range(entries):
                hour = rng.choices(range(24), _HOURLY_WEIGHTS)[0]
                entry = datetime.combine(day, datetime.min.time()) + timedelta(
                    hours=hour, minutes=rng.randint(0, 59), seconds=rng.randint(0, 59)
                )
                if entry >= now:
                    continue
                stay = timedelta(minutes=max(5, int(rng.lognormvariate(4.3, 0.8))))
                if rng.random() < 0.03:
                    stay += timedelta(hours=rng.randint(12, 40))
                exit_ = entry + stay

                if rng.random() < 0.06:
                    plate = rng.choice(list(registry))
                    vehicle = registry[plate]
                    vtype = vehicle.vehicle_type
                else:
                    plate, vtype, vehicle = random_plate(rng), random_vehicle_type(rng), None
                if plate in open_plates:
                    continue

                still_inside = exit_ >= now
                if still_inside and len(open_plates) >= int(capacity * 0.8):
                    continue
                session = ParkingSession(
                    plate=plate,
                    vehicle_id=vehicle.id if vehicle else None,
                    vehicle_type=vtype,
                    entry_time=entry,
                    entry_camera=_ENTRY_CAMERA,
                    entry_confidence=round(rng.uniform(0.86, 0.99), 3),
                    status=SessionStatus.OPEN,
                )
                if still_inside:
                    open_plates.add(plate)
                else:
                    _close(session, vehicle, exit_, tariffs, vtype, rng)
                s.add(session)
                s.flush()
                count += 1
                s.add(_event(session, EventAction.ENTRY, entry, _ENTRY_CAMERA))
                if not still_inside:
                    s.add(_event(session, EventAction.EXIT, exit_, _EXIT_CAMERA))
    return count


def _close(session, vehicle, exit_, tariffs, vtype, rng) -> None:
    session.status = SessionStatus.CLOSED
    session.exit_time = exit_
    session.exit_camera = _EXIT_CAMERA
    session.exit_confidence = round(rng.uniform(0.86, 0.99), 3)
    if vehicle is not None and vehicle.is_subscriber:
        session.fee = Decimal("0.00")
        session.payment_method = PaymentMethod.SUBSCRIPTION
    else:
        rule = tariffs.get(vtype) or tariffs[VehicleType.UNKNOWN]
        session.fee = rule.fee_between(session.entry_time, exit_)
        if session.fee == 0:
            session.payment_method = PaymentMethod.FREE
        elif rng.random() < 0.03:
            return  # ödenmemiş
        else:
            session.payment_method = rng.choices((PaymentMethod.CARD, PaymentMethod.CASH), (7, 3))[
                0
            ]
    session.is_paid = True
    session.paid_at = exit_


def _event(session: ParkingSession, action: EventAction, when: datetime, camera: str):
    confidence = (
        session.entry_confidence if action is EventAction.ENTRY else session.exit_confidence
    )
    return DetectionEvent(
        timestamp=when,
        camera_name=camera,
        plate=session.plate,
        raw_text=session.plate,
        confidence=confidence,
        vehicle_type=session.vehicle_type,
        action=action,
        session_id=session.id,
        message=f"{action.label}: {format_plate(session.plate)} — {session.vehicle_type.label}",
    )
