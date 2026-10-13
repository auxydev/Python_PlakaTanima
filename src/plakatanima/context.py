"""Uygulama bileşenlerini (ayar, veritabanı, servisler) bir araya getirir."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from plakatanima.config import AppConfig, load_config
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

    @classmethod
    def create(cls, config_path: Path | None = None, paths: AppPaths | None = None) -> AppContext:
        paths = (paths or default_paths()).ensure()
        config_path = config_path or paths.config_file
        config = load_config(config_path)
        db = Database(config.database.url or f"sqlite:///{paths.database_file}")
        db.create_schema()
        return cls(
            paths=paths,
            config_path=config_path,
            config=config,
            db=db,
            parking=ParkingService(db, config),
            vehicles=VehicleRegistry(db),
            tariffs=TariffService(db),
        )

    def save_config(self) -> None:
        self.config.save(self.config_path)

    def close(self) -> None:
        self.db.dispose()
