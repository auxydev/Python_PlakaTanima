"""Veritabanı tabloları (SQLAlchemy 2.0, tipli ORM).

Zamanlar yerel saat olarak (saat dilimi bilgisi olmadan) saklanır; otopark
raporları gün bazında yerel saate göre hazırlanır.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from plakatanima.core.pricing import TariffRule
from plakatanima.core.vehicle import VehicleType


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _enum(enum_cls: type[StrEnum], length: int = 24) -> Enum:
    # Değerler (ör. "otomobil") metin olarak saklanır; veritabanına özel enum tipi oluşturulmaz.
    return Enum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )


class Base(DeclarativeBase):
    pass


class SessionStatus(StrEnum):
    OPEN = "acik"
    CLOSED = "kapali"
    # Araç çıkışı okunamadı; aynı plaka tekrar girdiğinde eski kayıt otomatik kapatıldı.
    EXIT_MISSED = "cikis_okunamadi"

    @property
    def label(self) -> str:
        return {
            SessionStatus.OPEN: "İçeride",
            SessionStatus.CLOSED: "Çıktı",
            SessionStatus.EXIT_MISSED: "Çıkış okunamadı",
        }[self]


class PaymentMethod(StrEnum):
    CASH = "nakit"
    CARD = "kart"
    SUBSCRIPTION = "abone"
    FREE = "ucretsiz"

    @property
    def label(self) -> str:
        return {
            PaymentMethod.CASH: "Nakit",
            PaymentMethod.CARD: "Kredi Kartı",
            PaymentMethod.SUBSCRIPTION: "Abone",
            PaymentMethod.FREE: "Ücretsiz",
        }[self]


class EventAction(StrEnum):
    ENTRY = "giris"
    EXIT = "cikis"
    # Aynı geçişin tekrar okunması; kayıt oluşturulmadı.
    DUPLICATE = "tekrar"
    # Çıkış kamerası, içeride kaydı olmayan bir plaka okudu.
    UNMATCHED_EXIT = "eslesmeyen_cikis"

    @property
    def label(self) -> str:
        return {
            EventAction.ENTRY: "Giriş",
            EventAction.EXIT: "Çıkış",
            EventAction.DUPLICATE: "Tekrar okuma",
            EventAction.UNMATCHED_EXIT: "Kayıtsız çıkış",
        }[self]


class UserRole(StrEnum):
    ADMIN = "yonetici"
    OPERATOR = "operator"

    @property
    def label(self) -> str:
        return {UserRole.ADMIN: "Yönetici", UserRole.OPERATOR: "Operatör"}[self]


class Vehicle(Base):
    """Kayıtlı araç (abone, kara liste, sahip bilgisi)."""

    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    plate: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    vehicle_type: Mapped[VehicleType] = mapped_column(
        _enum(VehicleType), default=VehicleType.UNKNOWN
    )
    owner_name: Mapped[str] = mapped_column(String(120), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    brand_model: Mapped[str] = mapped_column(String(80), default="")
    color: Mapped[str] = mapped_column(String(40), default="")
    is_subscriber: Mapped[bool] = mapped_column(Boolean, default=False)
    subscription_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, default=False)
    blacklist_reason: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    sessions: Mapped[list[ParkingSession]] = relationship(back_populates="vehicle")

    def has_active_subscription(self, on: date | None = None) -> bool:
        if not self.is_subscriber:
            return False
        on = on or date.today()
        return self.subscription_end is None or self.subscription_end >= on


class ParkingSession(Base):
    """Bir aracın otoparka girişi ile çıkışı arasındaki kayıt."""

    __tablename__ = "parking_sessions"
    __table_args__ = (
        # Bir plakanın aynı anda yalnızca bir açık kaydı olabilir.
        Index(
            "uq_parking_sessions_open_plate",
            "plate",
            unique=True,
            sqlite_where=text("status = 'acik'"),
            postgresql_where=text("status = 'acik'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plate: Mapped[str] = mapped_column(String(16), index=True)
    vehicle_id: Mapped[int | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True
    )
    vehicle_type: Mapped[VehicleType] = mapped_column(
        _enum(VehicleType), default=VehicleType.UNKNOWN
    )
    status: Mapped[SessionStatus] = mapped_column(
        _enum(SessionStatus), default=SessionStatus.OPEN, index=True
    )

    entry_time: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    entry_camera: Mapped[str] = mapped_column(String(80), default="")
    entry_image: Mapped[str | None] = mapped_column(String(255), nullable=True)
    entry_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_manual_entry: Mapped[bool] = mapped_column(Boolean, default=False)

    exit_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    exit_camera: Mapped[str] = mapped_column(String(80), default="")
    exit_image: Mapped[str | None] = mapped_column(String(255), nullable=True)
    exit_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_manual_exit: Mapped[bool] = mapped_column(Boolean, default=False)

    fee: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    payment_method: Mapped[PaymentMethod | None] = mapped_column(
        _enum(PaymentMethod), nullable=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str] = mapped_column(String(255), default="")

    vehicle: Mapped[Vehicle | None] = relationship(back_populates="sessions")

    @property
    def is_open(self) -> bool:
        return self.status is SessionStatus.OPEN

    def duration(self, now: datetime | None = None) -> timedelta:
        end = self.exit_time or now or datetime.now()
        return max(end - self.entry_time, timedelta(0))


class Tariff(Base):
    """Araç tipine göre ücret tarifesi."""

    __tablename__ = "tariffs"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_type: Mapped[VehicleType] = mapped_column(_enum(VehicleType), unique=True)
    free_minutes: Mapped[int] = mapped_column(Integer, default=15)
    first_hour_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    additional_hour_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    daily_max_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal(0))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    def to_rule(self) -> TariffRule:
        return TariffRule(
            free_minutes=self.free_minutes,
            first_hour_fee=Decimal(self.first_hour_fee),
            additional_hour_fee=Decimal(self.additional_hour_fee),
            daily_max_fee=Decimal(self.daily_max_fee or 0),
        )


class DetectionEvent(Base):
    """Kameradan veya operatörden gelen her plaka işleminin günlüğü."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    camera_name: Mapped[str] = mapped_column(String(80), default="")
    plate: Mapped[str] = mapped_column(String(16), index=True)
    raw_text: Mapped[str] = mapped_column(String(32), default="")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    vehicle_type: Mapped[VehicleType] = mapped_column(
        _enum(VehicleType), default=VehicleType.UNKNOWN
    )
    action: Mapped[EventAction] = mapped_column(_enum(EventAction))
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, default=False)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("parking_sessions.id", ondelete="SET NULL"), nullable=True
    )
    image_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message: Mapped[str] = mapped_column(String(255), default="")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(_enum(UserRole), default=UserRole.OPERATOR)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
