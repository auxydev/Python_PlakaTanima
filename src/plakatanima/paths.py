"""Uygulama dizinleri.

Varsayılan olarak işletim sisteminin kullanıcı veri/ayar dizinleri kullanılır.
``PLAKATANIMA_HOME`` ortam değişkeni verilirse tüm dosyalar (ayar, veritabanı,
modeller, görüntüler, loglar) o dizin altında tutulur (taşınabilir mod).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

from plakatanima import APP_NAME

HOME_ENV = "PLAKATANIMA_HOME"


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path
    data_dir: Path

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def database_file(self) -> Path:
        return self.data_dir / "plakatanima.db"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def captures_dir(self) -> Path:
        return self.data_dir / "captures"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    def ensure(self) -> AppPaths:
        for path in (
            self.config_dir,
            self.data_dir,
            self.models_dir,
            self.captures_dir,
            self.logs_dir,
            self.backups_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return self


def default_paths() -> AppPaths:
    home = os.environ.get(HOME_ENV)
    if home:
        root = Path(home).expanduser().resolve()
        return AppPaths(config_dir=root, data_dir=root / "data")
    return AppPaths(
        config_dir=Path(user_config_dir(APP_NAME, appauthor=False)),
        data_dir=Path(user_data_dir(APP_NAME, appauthor=False)),
    )
