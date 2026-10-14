"""Arayüzün iş akışlarını (kamera olayları, ödeme, manuel geçiş) yöneten denetleyici."""

from __future__ import annotations

import logging
import random

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QWidget

from plakatanima.camera.manager import CameraManager
from plakatanima.config import CameraRole
from plakatanima.context import AppContext
from plakatanima.core.formatting import format_money
from plakatanima.core.plate import format_plate
from plakatanima.db.models import EventAction, PaymentMethod, SessionStatus, User, UserRole
from plakatanima.gui.bridge import CameraBridge
from plakatanima.gui.dialogs import ManualPassDialog, PaymentDialog, SessionDetailDialog
from plakatanima.gui.utils import confirm, show_error
from plakatanima.gui.widgets.toast import ToastManager
from plakatanima.services.parking import ParkingResult, PlateObservation

log = logging.getLogger(__name__)


class Controller(QObject):
    #: Yeni giriş/çıkış işlendi
    result_added = Signal(object)
    #: Kayıtlar değişti (ödeme, silme, araç kaydı ...): sayfalar yenilensin
    data_changed = Signal()
    #: Kamera listesi yeniden oluşturuldu
    cameras_restarted = Signal()

    def __init__(self, ctx: AppContext, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.bridge = CameraBridge(self)
        self.bridge.plate_confirmed.connect(self._on_plate)
        self.cameras = CameraManager(
            ctx.config,
            ctx.paths,
            self.bridge.callbacks(),
            inside_vehicles=ctx.inside_vehicles,
            registered_vehicles=ctx.registered_vehicles,
        )
        self.window: QWidget | None = None
        self.toasts: ToastManager | None = None
        self.current_user: User | None = None

    @property
    def is_admin(self) -> bool:
        """Giriş kapalıysa (tek kullanıcılı kurulum) tüm yetkiler açıktır."""
        return self.current_user is None or self.current_user.role is UserRole.ADMIN

    @property
    def currency(self) -> str:
        return self.ctx.config.parking.currency

    def attach(self, window: QWidget) -> None:
        self.window = window
        self.toasts = ToastManager(window)

    # ------------------------------------------------------------ kameralar
    def start_cameras(self) -> None:
        self.cameras.start()
        self.cameras_restarted.emit()

    def stop_cameras(self) -> None:
        self.cameras.stop()

    def _on_plate(self, _index: int, observation: PlateObservation, _confirmed) -> None:
        self.process(observation)

    # ------------------------------------------------------------- işlemler
    def process(self, observation: PlateObservation) -> ParkingResult | None:
        try:
            result = self.ctx.parking.process(observation)
        except Exception as exc:
            log.exception("Plaka işlenemedi")
            self.toast("İşlem başarısız", str(exc), "danger")
            return None
        self.result_added.emit(result)
        self._notify(result)
        return result

    def _notify(self, result: ParkingResult) -> None:
        plate = format_plate(result.plate)
        if result.is_blacklisted:
            QApplication.beep()
            reason = f" — {result.blacklist_reason}" if result.blacklist_reason else ""
            self.toast(
                "KARA LİSTE ARACI",
                f"{plate} {result.action.label.lower()} yaptı ({result.camera_name}){reason}",
                "danger",
                timeout_ms=15000,
            )
        if result.lot_full:
            self.toast("Otopark dolu", f"{plate} kapasite dolduğu halde giriş yaptı.", "warning")
        if result.action is EventAction.UNMATCHED_EXIT:
            self.toast(
                "Giriş kaydı yok",
                f"{plate} için açık giriş kaydı bulunamadı ({result.camera_name}).",
                "warning",
            )
        if result.needs_payment and result.session_id is not None and self.ctx.demo:
            # Demo modunda çıkıştaki ödeme otomatik (ödeme makinesi gibi) alınır.
            session_id = result.session_id
            QTimer.singleShot(2500, lambda: self._demo_payment(session_id))
        elif result.needs_payment and result.session_id is not None:
            session_id = result.session_id
            self.toast(
                f"Ödeme bekleniyor: {plate}",
                f"{result.vehicle_type.label} · {format_money(result.fee, self.currency)}",
                "info",
                action=("Ödeme Al", lambda: self.collect_payment(session_id)),
                timeout_ms=20000,
            )

    def _demo_payment(self, session_id: int) -> None:
        method = random.choices((PaymentMethod.CARD, PaymentMethod.CASH), (7, 3))[0]
        try:
            self.ctx.parking.record_payment(session_id, method)
        except LookupError:
            return
        self.data_changed.emit()

    def toast(self, title: str, text: str, level: str = "info", **kwargs) -> None:
        if self.toasts is not None:
            self.toasts.show(title, text, level, **kwargs)

    def manual_pass(self, role: CameraRole = CameraRole.ENTRY, plate: str = "") -> None:
        dialog = ManualPassDialog(self.window, role=role, plate=plate)
        if dialog.exec() and dialog.observation is not None:
            result = self.process(dialog.observation)
            if result is not None and result.action not in (EventAction.ENTRY, EventAction.EXIT):
                self.toast(result.action.label, result.message, "warning")
            elif result is not None and result.needs_payment and result.session_id:
                self.collect_payment(result.session_id)

    def exit_session(self, session_id: int) -> None:
        session = self.ctx.parking.get_session(session_id)
        if session is None or session.status is not SessionStatus.OPEN:
            return
        if not confirm(
            self.window, "Çıkış", f"{format_plate(session.plate)} için çıkış yapılsın mı?"
        ):
            return
        result = self.process(
            PlateObservation(
                plate=session.plate,
                role=CameraRole.EXIT,
                vehicle_type=session.vehicle_type,
                manual=True,
            )
        )
        if result is not None and result.needs_payment and result.session_id:
            self.collect_payment(result.session_id)

    def collect_payment(self, session_id: int) -> None:
        session = self.ctx.parking.get_session(session_id)
        if session is None:
            return
        if session.is_paid:
            self.toast("Ödeme alınmış", f"{format_plate(session.plate)} ödemesi zaten kayıtlı.")
            return
        fee = session.fee if session.fee is not None else self.ctx.parking.current_fee(session_id)
        dialog = PaymentDialog(session, fee, self.currency, self.window)
        if dialog.exec() and dialog.method is not None:
            self.ctx.parking.record_payment(session_id, dialog.method, dialog.amount_value())
            amount = format_money(dialog.amount_value(), self.currency)
            self.toast(
                "Ödeme alındı",
                f"{format_plate(session.plate)} · {amount} · {dialog.method.label}",
                "success",
            )
            self.data_changed.emit()

    def show_session(self, session_id: int) -> None:
        session = self.ctx.parking.get_session(session_id)
        if session is None:
            show_error(self.window, "Kayıt bulunamadı (silinmiş olabilir).")
            return
        current = None
        if session.status is SessionStatus.OPEN:
            current = self.ctx.parking.current_fee(session_id)
        dialog = SessionDetailDialog(
            session,
            self.ctx.paths.captures_dir,
            self.currency,
            current_fee=current,
            can_delete=self.is_admin,
            parent=self.window,
        )
        if not dialog.exec():
            return
        if dialog.action == "exit":
            self.exit_session(session_id)
        elif dialog.action == "pay":
            self.collect_payment(session_id)
        elif dialog.action == "type" and dialog.new_type is not None:
            self.ctx.parking.set_session_vehicle_type(session_id, dialog.new_type)
            self.data_changed.emit()
        elif dialog.action == "delete" and confirm(
            self.window, "Kaydı sil", f"#{session_id} numaralı kayıt silinsin mi?"
        ):
            self.ctx.parking.delete_session(session_id)
            self.data_changed.emit()

    def shutdown(self) -> None:
        self.cameras.stop()
