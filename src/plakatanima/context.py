"""Uygulama bileşenlerini (ayar, veritabanı, servisler) bir araya getirir."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from plakatanima.config import AppConfig, CameraConfig, CameraRole, load_config
from plakatanima.core.vehicle import VehicleType
from plakatanima.db.database import Database
from plakatanima.paths import AppPaths, default_paths
from plakatanima.services.parking import ParkingService
from plakatanima.services.registry import TariffService, VehicleRegistry


@dataclass
class AppContext:
    paths: AppPaths
    config_path: Path
    config: AppConfig
    db: Database
    parking: ParkingService
    vehicles: VehicleRegistry
    tariffs: TariffService
    demo: bool = False

    @classmethod
    def create(
        cls,
        config_path: Path | None = None,
        paths: AppPaths | None = None,
        *,
        demo: bool = False,
    ) -> AppContext:
        paths = paths or default_paths()
        if demo:
            paths = paths.demo()
            config_path = paths.config_file
            if not config_path.exists():
                demo_config().save(config_path)
        paths.ensure()
        config_path = config_path or paths.config_file
        config = load_config(config_path)
        db = Database(config.database.url or f"sqlite:///{paths.database_file}")
        db.create_schema()
        if demo:
            from plakatanima.demo.seed import has_sessions, seed_demo_data

            if not has_sessions(db):
                seed_demo_data(db, capacity=config.parking.capacity)
        return cls(
            paths=paths,
            config_path=config_path,
            config=config,
            db=db,
            parking=ParkingService(db, config),
            vehicles=VehicleRegistry(db),
            tariffs=TariffService(db),
            demo=demo,
        )

    def inside_vehicles(self) -> list[tuple[str, VehicleType, datetime]]:
        return [(s.plate, s.vehicle_type, s.entry_time) for s in self.parking.open_sessions()]

    def registered_vehicles(self) -> list[tuple[str, VehicleType]]:
        return [(v.plate, v.vehicle_type) for v in self.vehicles.search()]

    def save_config(self) -> None:
        self.config.save(self.config_path)

    def close(self) -> None:
        self.db.dispose()


def demo_config() -> AppConfig:
    config = AppConfig()
    config.parking.lot_name = "Demo Otopark"
    config.parking.capacity = 120
    config.ui.require_login = False
    config.cameras = [
        CameraConfig(name="Giriş Kamerası", source="demo", role=CameraRole.ENTRY),
        CameraConfig(name="Çıkış Kamerası", source="demo", role=CameraRole.EXIT),
    ]
    return config
