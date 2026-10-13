"""Uygulama ayarları (TOML dosyasında saklanır, pydantic ile doğrulanır)."""

from __future__ import annotations

import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Literal

import tomli_w
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class ConfigError(RuntimeError):
    """Ayar dosyası okunamadığında veya geçersiz olduğunda fırlatılır."""


class CameraRole(StrEnum):
    """Kameranın otoparktaki görevi."""

    ENTRY = "giris"
    EXIT = "cikis"
    # Tek kamera ile hem giriş hem çıkış: açık kaydı olan araç çıkış, olmayan giriş sayılır.
    BOTH = "giris_cikis"

    @property
    def label(self) -> str:
        return {
            CameraRole.ENTRY: "Giriş",
            CameraRole.EXIT: "Çıkış",
            CameraRole.BOTH: "Giriş / Çıkış",
        }[self]


class _Section(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=True)


class CameraConfig(_Section):
    name: str = "Giriş Kamerası"
    # Webcam numarası ("0"), RTSP/HTTP adresi, video dosyası yolu veya "demo".
    source: str = "0"
    role: CameraRole = CameraRole.ENTRY
    enabled: bool = True
    # Saniyede kaç karenin tanıma için işleneceği (görüntü akışı bundan bağımsızdır).
    process_fps: float = Field(default=4.0, gt=0, le=60)
    # Normalleştirilmiş ilgi alanı (x1, y1, x2, y2), 0-1 aralığında. Boşsa tüm kare.
    roi: tuple[float, float, float, float] | None = None

    @field_validator("roi")
    @classmethod
    def _check_roi(cls, value: tuple[float, float, float, float] | None):
        if value is None:
            return value
        x1, y1, x2, y2 = value
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            raise ValueError("roi 0-1 aralığında (x1, y1, x2, y2) olmalı ve x1<x2, y1<y2")
        return value


class RecognitionConfig(_Section):
    # Araç tespiti/sınıflandırma: "yolox" (ONNX, varsayılan), "ultralytics" (opsiyonel), "none"
    vehicle_detector: Literal["yolox", "ultralytics", "none"] = "yolox"
    # yolox için: yolox_nano | yolox_tiny | yolox_s | yolox_m veya .onnx yolu
    # ultralytics için: yolo11n.pt gibi model adı veya .pt yolu
    vehicle_model: str = "yolox_s"
    vehicle_confidence: float = Field(default=0.35, ge=0.05, le=0.99)
    plate_detector_model: str = "yolo-v9-t-384-license-plate-end2end"
    plate_detector_confidence: float = Field(default=0.4, ge=0.05, le=0.99)
    ocr_model: str = "cct-xs-v2-global-model"
    # Bir okumanın oylamaya katılması için gereken en düşük OCR güveni.
    min_ocr_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    # Bir plakanın onaylanması için kaç farklı karede okunması gerektiği.
    min_hits: int = Field(default=3, ge=1, le=50)
    # Okumaların aynı araca ait sayılacağı en uzun boşluk (saniye).
    track_timeout_seconds: float = Field(default=2.5, gt=0)
    # Aynı plakanın aynı kamerada tekrar işlenmeyeceği süre (saniye).
    cooldown_seconds: float = Field(default=30.0, ge=0)
    # True ise yalnızca Türk plaka formatına uyan okumalar kabul edilir.
    turkish_plates_only: bool = True
    device: Literal["auto", "cpu", "cuda"] = "auto"


class ParkingConfig(_Section):
    lot_name: str = "Otopark"
    capacity: int = Field(default=100, ge=1)
    # Aynı kamera hem giriş hem çıkışsa, girişten sonra bu süre dolmadan çıkış sayılmaz.
    min_stay_seconds: int = Field(default=120, ge=0)
    currency: str = "TL"
    save_snapshots: bool = True
    snapshot_retention_days: int = Field(default=90, ge=1)


class DatabaseConfig(_Section):
    # Boşsa veri dizinindeki SQLite dosyası kullanılır.
    # Örn: "postgresql+psycopg://kullanici:sifre@localhost/otopark"
    url: str | None = None


class UIConfig(_Section):
    theme: Literal["dark", "light"] = "dark"
    require_login: bool = True
    # Ana sayfadaki "son geçişler" listesinde gösterilecek kayıt sayısı.
    recent_events_limit: int = Field(default=50, ge=5, le=500)


def _default_cameras() -> list[CameraConfig]:
    return [CameraConfig()]


class AppConfig(_Section):
    parking: ParkingConfig = Field(default_factory=ParkingConfig)
    recognition: RecognitionConfig = Field(default_factory=RecognitionConfig)
    cameras: list[CameraConfig] = Field(default_factory=_default_cameras)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    ui: UIConfig = Field(default_factory=UIConfig)

    def to_toml(self) -> str:
        # TOML'da null yoktur; None alanlar dosyaya yazılmaz, okurken varsayılana döner.
        return tomli_w.dumps(self.model_dump(mode="json", exclude_none=True))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(self.to_toml(), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def from_toml(cls, text: str) -> AppConfig:
        try:
            return cls.model_validate(tomllib.loads(text))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"Ayar dosyası okunamadı: {exc}") from exc
        except ValidationError as exc:
            raise ConfigError(f"Ayar dosyası geçersiz:\n{exc}") from exc


def load_config(path: Path, *, create: bool = True) -> AppConfig:
    """Ayarları okur. Dosya yoksa varsayılanları kullanır (ve ``create`` ise dosyayı yazar)."""
    if not path.exists():
        config = AppConfig()
        if create:
            config.save(path)
        return config
    return AppConfig.from_toml(path.read_text(encoding="utf-8"))
