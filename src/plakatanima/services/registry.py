"""Araç kayıtları (abone / kara liste) ve tarife yönetimi."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select

from plakatanima.core.plate import clean_text
from plakatanima.core.vehicle import VehicleType
from plakatanima.db.database import Database
from plakatanima.db.models import Tariff, Vehicle


@dataclass(slots=True)
class VehicleData:
    """Araç formundan gelen veriler."""

    plate: str
    vehicle_type: VehicleType = VehicleType.UNKNOWN
    owner_name: str = ""
    phone: str = ""
    brand_model: str = ""
    color: str = ""
    is_subscriber: bool = False
    subscription_end: date | None = None
    is_blacklisted: bool = False
    blacklist_reason: str = ""
    notes: str = ""

    @classmethod
    def from_vehicle(cls, vehicle: Vehicle) -> VehicleData:
        return cls(**{f.name: getattr(vehicle, f.name) for f in fields(cls)})


class VehicleRegistry:
    def __init__(self, db: Database) -> None:
        self._db = db

    def search(
        self,
        query: str = "",
        *,
        subscribers_only: bool = False,
        blacklisted_only: bool = False,
    ) -> list[Vehicle]:
        stmt = select(Vehicle)
        if query:
            like = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(
                    Vehicle.plate.contains(clean_text(query)),
                    Vehicle.owner_name.ilike(like),
                    Vehicle.phone.ilike(like),
                    Vehicle.brand_model.ilike(like),
                )
            )
        if subscribers_only:
            stmt = stmt.where(Vehicle.is_subscriber.is_(True))
        if blacklisted_only:
            stmt = stmt.where(Vehicle.is_blacklisted.is_(True))
        with self._db.session() as s:
            return list(s.scalars(stmt.order_by(Vehicle.plate)))

    def get(self, plate: str) -> Vehicle | None:
        with self._db.session() as s:
            return s.scalar(select(Vehicle).where(Vehicle.plate == clean_text(plate)))

    def save(self, data: VehicleData, vehicle_id: int | None = None) -> Vehicle:
        """Yeni araç ekler veya ``vehicle_id`` verilen kaydı günceller."""
        plate = clean_text(data.plate)
        if not plate:
            raise ValueError("Plaka boş olamaz")
        with self._db.session() as s:
            clash = s.scalar(select(Vehicle).where(Vehicle.plate == plate))
            if clash is not None and clash.id != vehicle_id:
                raise ValueError(f"{plate} plakalı araç zaten kayıtlı")
            if vehicle_id is None:
                vehicle = Vehicle(plate=plate)
                s.add(vehicle)
            else:
                vehicle = s.get(Vehicle, vehicle_id)
                if vehicle is None:
                    raise LookupError(f"Araç bulunamadı: {vehicle_id}")
            for f in fields(VehicleData):
                setattr(vehicle, f.name, getattr(data, f.name))
            vehicle.plate = plate
            vehicle.vehicle_type = VehicleType.parse(data.vehicle_type)
            if not vehicle.is_blacklisted:
                vehicle.blacklist_reason = ""
            s.flush()
            return vehicle

    def delete(self, vehicle_id: int) -> None:
        with self._db.session() as s:
            vehicle = s.get(Vehicle, vehicle_id)
            if vehicle is not None:
                s.delete(vehicle)


class TariffService:
    def __init__(self, db: Database) -> None:
        self._db = db

    def all(self) -> list[Tariff]:
        order = {vtype: i for i, vtype in enumerate(VehicleType)}
        with self._db.session() as s:
            return sorted(s.scalars(select(Tariff)), key=lambda t: order[t.vehicle_type])

    def update(
        self,
        vehicle_type: VehicleType,
        *,
        free_minutes: int,
        first_hour_fee: Decimal,
        additional_hour_fee: Decimal,
        daily_max_fee: Decimal,
    ) -> Tariff:
        if free_minutes < 0 or min(first_hour_fee, additional_hour_fee, daily_max_fee) < 0:
            raise ValueError("Tarife değerleri negatif olamaz")
        with self._db.session() as s:
            tariff = s.scalar(select(Tariff).where(Tariff.vehicle_type == vehicle_type))
            if tariff is None:
                tariff = Tariff(vehicle_type=vehicle_type)
                s.add(tariff)
            tariff.free_minutes = free_minutes
            tariff.first_hour_fee = first_hour_fee
            tariff.additional_hour_fee = additional_hour_fee
            tariff.daily_max_fee = daily_max_fee
            s.flush()
            return tariff
