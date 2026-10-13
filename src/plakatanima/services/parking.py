"""Giriş/çıkış iş kuralları.

Kameradan (veya operatörden) gelen her plaka okuması :class:`PlateObservation`
olarak :meth:`ParkingService.process` metoduna verilir. Servis kameranın
görevine (giriş, çıkış, ikisi birden) ve aracın içeride açık kaydı olup
olmamasına göre giriş, çıkış veya tekrar okuma kararı verir, kaydı
veritabanına yazar ve arayüzde gösterilecek bir :class:`ParkingResult` döndürür.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from plakatanima.config import AppConfig, CameraRole
from plakatanima.core.formatting import format_duration, format_money
from plakatanima.core.plate import clean_text, format_plate
from plakatanima.core.pricing import DEFAULT_TARIFFS, TariffRule
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

log = logging.getLogger(__name__)

OPERATOR_CAMERA = "Operatör"


def _now() -> datetime:
    return datetime.now()


@dataclass(slots=True)
class PlateObservation:
    """Onaylanmış bir plaka okuması (kamera) veya operatör girişi."""

    plate: str
    camera_name: str = OPERATOR_CAMERA
    role: CameraRole = CameraRole.ENTRY
    vehicle_type: VehicleType = VehicleType.UNKNOWN
    confidence: float | None = None
    raw_text: str = ""
    image_path: str | None = None
    timestamp: datetime | None = None
    manual: bool = False


@dataclass(slots=True)
class ParkingResult:
    action: EventAction
    plate: str
    camera_name: str
    timestamp: datetime
    vehicle_type: VehicleType
    message: str
    session_id: int | None = None
    event_id: int | None = None
    fee: Decimal | None = None
    duration: timedelta | None = None
    is_paid: bool = False
    is_blacklisted: bool = False
    blacklist_reason: str = ""
    is_subscriber: bool = False
    owner_name: str = ""
    lot_full: bool = False
    image_path: str | None = None
    confidence: float | None = None

    @property
    def is_alert(self) -> bool:
        return self.is_blacklisted or self.lot_full or self.action is EventAction.UNMATCHED_EXIT

    @property
    def needs_payment(self) -> bool:
        return self.action is EventAction.EXIT and not self.is_paid and bool(self.fee)


@dataclass(slots=True)
class DashboardStats:
    inside: int
    capacity: int
    entries_today: int
    exits_today: int
    revenue_today: Decimal
    unpaid_count: int
    inside_by_type: dict[VehicleType, int] = field(default_factory=dict)
    entries_by_type_today: dict[VehicleType, int] = field(default_factory=dict)

    @property
    def free_spaces(self) -> int:
        return max(self.capacity - self.inside, 0)

    @property
    def occupancy_ratio(self) -> float:
        return min(self.inside / self.capacity, 1.0) if self.capacity else 0.0


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min)
    return start, start + timedelta(days=1)


class ParkingService:
    def __init__(
        self,
        db: Database,
        config: AppConfig,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._db = db
        self._config = config
        self._clock = clock

    # ------------------------------------------------------------------ işlem
    def process(self, obs: PlateObservation) -> ParkingResult:
        now = (obs.timestamp or self._clock()).replace(microsecond=0)
        plate = clean_text(obs.plate)
        if not plate:
            raise ValueError("Plaka boş olamaz")

        with self._db.session() as s:
            vehicle = s.scalar(select(Vehicle).where(Vehicle.plate == plate))
            open_session = self._open_session(s, plate)
            action = self._decide(s, obs, plate, open_session, now)

            if action is EventAction.ENTRY:
                result = self._enter(s, obs, plate, vehicle, open_session, now)
            elif action is EventAction.EXIT:
                assert open_session is not None
                result = self._exit(s, obs, open_session, vehicle, now)
            else:
                result = self._ignored(obs, plate, vehicle, open_session, action, now)

            event = DetectionEvent(
                timestamp=now,
                camera_name=obs.camera_name,
                plate=plate,
                raw_text=obs.raw_text[:32],
                confidence=obs.confidence,
                vehicle_type=result.vehicle_type,
                action=action,
                is_manual=obs.manual,
                is_blacklisted=result.is_blacklisted,
                session_id=result.session_id,
                image_path=obs.image_path,
                message=result.message[:255],
            )
            s.add(event)
            s.flush()
            result.event_id = event.id

        log.info("[%s] %s", obs.camera_name, result.message)
        return result

    def _decide(
        self,
        s: Session,
        obs: PlateObservation,
        plate: str,
        open_session: ParkingSession | None,
        now: datetime,
    ) -> EventAction:
        min_stay = timedelta(seconds=self._config.parking.min_stay_seconds)
        role = obs.role

        if obs.manual:
            if role is CameraRole.EXIT or (role is CameraRole.BOTH and open_session):
                return EventAction.EXIT if open_session else EventAction.UNMATCHED_EXIT
            return EventAction.DUPLICATE if open_session else EventAction.ENTRY

        if role is CameraRole.BOTH:
            if open_session is not None:
                if now - open_session.entry_time < min_stay:
                    return EventAction.DUPLICATE
                return EventAction.EXIT
            if self._recently_closed(s, plate, now - min_stay):
                return EventAction.DUPLICATE
            return EventAction.ENTRY

        if role is CameraRole.ENTRY:
            if open_session is not None and now - open_session.entry_time < min_stay:
                return EventAction.DUPLICATE
            # Daha eski açık kayıt varsa çıkışı kaçırılmıştır; _enter onu kapatır.
            return EventAction.ENTRY

        if open_session is not None:
            return EventAction.EXIT
        if self._recently_closed(s, plate, now - min_stay):
            return EventAction.DUPLICATE
        return EventAction.UNMATCHED_EXIT

    def _enter(
        self,
        s: Session,
        obs: PlateObservation,
        plate: str,
        vehicle: Vehicle | None,
        stale_session: ParkingSession | None,
        now: datetime,
    ) -> ParkingResult:
        notes: list[str] = []
        if stale_session is not None:
            stale_session.status = SessionStatus.EXIT_MISSED
            stale_session.exit_time = now
            stale_session.note = "Çıkış okunamadı; araç yeniden giriş yaptı"
            s.flush()
            notes.append("önceki kaydın çıkışı okunamamıştı")

        vehicle_type = obs.vehicle_type
        if vehicle is not None and vehicle.vehicle_type is not VehicleType.UNKNOWN:
            vehicle_type = vehicle.vehicle_type

        inside = self._inside_count(s)
        lot_full = inside >= self._config.parking.capacity

        session = ParkingSession(
            plate=plate,
            vehicle_id=vehicle.id if vehicle else None,
            vehicle_type=vehicle_type,
            status=SessionStatus.OPEN,
            entry_time=now,
            entry_camera=obs.camera_name,
            entry_image=obs.image_path,
            entry_confidence=obs.confidence,
            is_manual_entry=obs.manual,
        )
        s.add(session)
        s.flush()

        result = self._base_result(obs, plate, vehicle, EventAction.ENTRY, vehicle_type, now)
        result.session_id = session.id
        result.lot_full = lot_full
        if lot_full:
            notes.append("OTOPARK DOLU")
        result.message = self._message(result, f"Giriş: {format_plate(plate)}", notes)
        return result

    def _exit(
        self,
        s: Session,
        obs: PlateObservation,
        session: ParkingSession,
        vehicle: Vehicle | None,
        now: datetime,
    ) -> ParkingResult:
        if session.vehicle_type is VehicleType.UNKNOWN and obs.vehicle_type is not (
            VehicleType.UNKNOWN
        ):
            session.vehicle_type = obs.vehicle_type

        session.status = SessionStatus.CLOSED
        session.exit_time = now
        session.exit_camera = obs.camera_name
        session.exit_image = obs.image_path
        session.exit_confidence = obs.confidence
        session.is_manual_exit = obs.manual

        subscriber = vehicle is not None and vehicle.has_active_subscription(now.date())
        if subscriber:
            session.fee = Decimal("0.00")
            session.payment_method = PaymentMethod.SUBSCRIPTION
        else:
            session.fee = self.tariff_rule(session.vehicle_type, s).fee_between(
                session.entry_time, now
            )
            if session.fee == 0:
                session.payment_method = PaymentMethod.FREE
        if session.payment_method is not None:
            session.is_paid = True
            session.paid_at = now
        s.flush()

        duration = now - session.entry_time
        result = self._base_result(
            obs, session.plate, vehicle, EventAction.EXIT, session.vehicle_type, now
        )
        result.session_id = session.id
        result.fee = session.fee
        result.duration = duration
        result.is_paid = session.is_paid
        currency = self._config.parking.currency
        notes = [format_duration(duration)]
        notes.append("ücretsiz" if not session.fee else format_money(session.fee, currency))
        result.message = self._message(result, f"Çıkış: {format_plate(session.plate)}", notes)
        return result

    def _ignored(
        self,
        obs: PlateObservation,
        plate: str,
        vehicle: Vehicle | None,
        open_session: ParkingSession | None,
        action: EventAction,
        now: datetime,
    ) -> ParkingResult:
        vehicle_type = open_session.vehicle_type if open_session else obs.vehicle_type
        result = self._base_result(obs, plate, vehicle, action, vehicle_type, now)
        result.session_id = open_session.id if open_session else None
        if action is EventAction.UNMATCHED_EXIT:
            head = f"Giriş kaydı bulunamadı: {format_plate(plate)}"
        elif obs.manual:
            head = f"Araç zaten içeride: {format_plate(plate)}"
        else:
            head = f"Tekrar okuma yok sayıldı: {format_plate(plate)}"
        result.message = self._message(result, head, [])
        return result

    def _base_result(
        self,
        obs: PlateObservation,
        plate: str,
        vehicle: Vehicle | None,
        action: EventAction,
        vehicle_type: VehicleType,
        now: datetime,
    ) -> ParkingResult:
        return ParkingResult(
            action=action,
            plate=plate,
            camera_name=obs.camera_name,
            timestamp=now,
            vehicle_type=vehicle_type,
            message="",
            is_blacklisted=bool(vehicle and vehicle.is_blacklisted),
            blacklist_reason=vehicle.blacklist_reason if vehicle else "",
            is_subscriber=bool(vehicle and vehicle.has_active_subscription(now.date())),
            owner_name=vehicle.owner_name if vehicle else "",
            image_path=obs.image_path,
            confidence=obs.confidence,
        )

    @staticmethod
    def _message(result: ParkingResult, head: str, notes: list[str]) -> str:
        parts = [head, result.vehicle_type.label, *notes]
        if result.is_subscriber:
            parts.append("abone")
        if result.is_blacklisted:
            reason = f" ({result.blacklist_reason})" if result.blacklist_reason else ""
            parts.append(f"KARA LİSTE{reason}")
        return " — ".join(parts)

    # ---------------------------------------------------------- yardımcılar
    @staticmethod
    def _open_session(s: Session, plate: str) -> ParkingSession | None:
        return s.scalar(
            select(ParkingSession).where(
                ParkingSession.plate == plate, ParkingSession.status == SessionStatus.OPEN
            )
        )

    @staticmethod
    def _recently_closed(s: Session, plate: str, since: datetime) -> bool:
        stmt = select(ParkingSession.id).where(
            ParkingSession.plate == plate,
            ParkingSession.status == SessionStatus.CLOSED,
            ParkingSession.exit_time >= since,
        )
        return s.scalar(stmt.limit(1)) is not None

    @staticmethod
    def _inside_count(s: Session) -> int:
        stmt = select(func.count()).where(ParkingSession.status == SessionStatus.OPEN)
        return s.scalar(stmt) or 0

    def tariff_rule(self, vehicle_type: VehicleType, s: Session | None = None) -> TariffRule:
        def lookup(session: Session) -> TariffRule:
            for candidate in (vehicle_type, VehicleType.UNKNOWN):
                tariff = session.scalar(select(Tariff).where(Tariff.vehicle_type == candidate))
                if tariff is not None:
                    return tariff.to_rule()
            return DEFAULT_TARIFFS[vehicle_type]

        if s is not None:
            return lookup(s)
        with self._db.session() as session:
            return lookup(session)

    # --------------------------------------------------------- operatör işleri
    def current_fee(self, session_id: int, at: datetime | None = None) -> Decimal:
        """İçerideki aracın şu ana kadar biriken ücreti (abonelere 0)."""
        at = at or self._clock()
        with self._db.session() as s:
            session = s.get(ParkingSession, session_id)
            if session is None:
                raise LookupError(f"Kayıt bulunamadı: {session_id}")
            if session.vehicle is not None and session.vehicle.has_active_subscription(at.date()):
                return Decimal("0.00")
            end = session.exit_time or at
            return self.tariff_rule(session.vehicle_type, s).fee_between(session.entry_time, end)

    def record_payment(
        self,
        session_id: int,
        method: PaymentMethod,
        amount: Decimal | None = None,
    ) -> ParkingSession:
        """Ödemeyi kaydeder. ``amount`` verilirse ücret bu tutarla değiştirilir (indirim)."""
        with self._db.session() as s:
            session = s.get(ParkingSession, session_id)
            if session is None:
                raise LookupError(f"Kayıt bulunamadı: {session_id}")
            if amount is not None:
                session.fee = Decimal(amount).quantize(Decimal("0.01"))
            session.is_paid = True
            session.payment_method = method
            session.paid_at = self._clock().replace(microsecond=0)
            return session

    def set_session_vehicle_type(self, session_id: int, vehicle_type: VehicleType) -> None:
        with self._db.session() as s:
            session = s.get(ParkingSession, session_id)
            if session is None:
                raise LookupError(f"Kayıt bulunamadı: {session_id}")
            session.vehicle_type = vehicle_type

    def delete_session(self, session_id: int) -> None:
        with self._db.session() as s:
            session = s.get(ParkingSession, session_id)
            if session is not None:
                s.delete(session)

    # ------------------------------------------------------------- sorgular
    def open_sessions(self) -> list[ParkingSession]:
        with self._db.session() as s:
            stmt = (
                select(ParkingSession)
                .options(selectinload(ParkingSession.vehicle))
                .where(ParkingSession.status == SessionStatus.OPEN)
                .order_by(ParkingSession.entry_time.desc())
            )
            return list(s.scalars(stmt))

    def find_sessions(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        plate: str = "",
        vehicle_type: VehicleType | None = None,
        status: SessionStatus | None = None,
        unpaid_only: bool = False,
        limit: int = 1000,
    ) -> list[ParkingSession]:
        """Giriş zamanı [start, end) aralığındaki kayıtlar, yeniden eskiye."""
        stmt = select(ParkingSession).options(selectinload(ParkingSession.vehicle))
        if start is not None:
            stmt = stmt.where(ParkingSession.entry_time >= start)
        if end is not None:
            stmt = stmt.where(ParkingSession.entry_time < end)
        if plate:
            stmt = stmt.where(ParkingSession.plate.contains(clean_text(plate)))
        if vehicle_type is not None:
            stmt = stmt.where(ParkingSession.vehicle_type == vehicle_type)
        if status is not None:
            stmt = stmt.where(ParkingSession.status == status)
        if unpaid_only:
            stmt = stmt.where(
                ParkingSession.status == SessionStatus.CLOSED,
                ParkingSession.is_paid.is_(False),
            )
        stmt = stmt.order_by(ParkingSession.entry_time.desc()).limit(limit)
        with self._db.session() as s:
            return list(s.scalars(stmt))

    def recent_events(self, limit: int = 50) -> list[DetectionEvent]:
        with self._db.session() as s:
            stmt = select(DetectionEvent).order_by(DetectionEvent.id.desc()).limit(limit)
            return list(s.scalars(stmt))

    def inside_count(self) -> int:
        with self._db.session() as s:
            return self._inside_count(s)

    def dashboard_stats(self, day: date | None = None) -> DashboardStats:
        day = day or self._clock().date()
        start, end = day_bounds(day)
        with self._db.session() as s:
            inside_by_type = self._count_by_type(s, ParkingSession.status == SessionStatus.OPEN)
            entries_by_type = self._count_by_type(
                s, ParkingSession.entry_time >= start, ParkingSession.entry_time < end
            )
            exits_today = s.scalar(
                select(func.count()).where(
                    ParkingSession.status == SessionStatus.CLOSED,
                    ParkingSession.exit_time >= start,
                    ParkingSession.exit_time < end,
                )
            )
            revenue = s.scalar(
                select(func.coalesce(func.sum(ParkingSession.fee), 0)).where(
                    ParkingSession.is_paid.is_(True),
                    ParkingSession.paid_at >= start,
                    ParkingSession.paid_at < end,
                )
            )
            unpaid = s.scalar(
                select(func.count()).where(
                    ParkingSession.status == SessionStatus.CLOSED,
                    ParkingSession.is_paid.is_(False),
                    or_(ParkingSession.fee.is_(None), ParkingSession.fee > 0),
                )
            )
        return DashboardStats(
            inside=sum(inside_by_type.values()),
            capacity=self._config.parking.capacity,
            entries_today=sum(entries_by_type.values()),
            exits_today=exits_today or 0,
            revenue_today=Decimal(revenue or 0).quantize(Decimal("0.01")),
            unpaid_count=unpaid or 0,
            inside_by_type=inside_by_type,
            entries_by_type_today=entries_by_type,
        )

    @staticmethod
    def _count_by_type(s: Session, *conditions) -> dict[VehicleType, int]:
        stmt = (
            select(ParkingSession.vehicle_type, func.count())
            .where(*conditions)
            .group_by(ParkingSession.vehicle_type)
        )
        return {VehicleType.parse(vtype): count for vtype, count in s.execute(stmt)}
