"""Geçiş kayıtları: tarih/plaka/tip/durum filtreli geçmiş."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from PySide6.QtCore import QDate, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from plakatanima.core.formatting import format_datetime, format_duration, format_money
from plakatanima.core.vehicle import VehicleType
from plakatanima.db.models import ParkingSession, SessionStatus
from plakatanima.gui import theme
from plakatanima.gui.controller import Controller
from plakatanima.gui.utils import button, enum_data, icon, muted, page_header
from plakatanima.gui.widgets.table import RIGHT, Column, DataTable, RowModel

MAX_ROWS = 5000


def _qdate(value: date) -> QDate:
    return QDate(value.year, value.month, value.day)


class SessionsPage(QWidget):
    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageRoot")
        self.controller = controller
        self.ctx = controller.ctx
        palette = theme.current()
        currency = self.ctx.config.parking.currency

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        detail = button("Ayrıntı", "mdi6.image-search-outline")
        detail.clicked.connect(self._detail_selected)
        pay = button("Ödeme Al", "mdi6.cash-register", variant="success")
        pay.clicked.connect(self._pay_selected)
        self.header_actions = [detail, pay]
        root.addWidget(
            page_header("Geçiş Kayıtları", "Tüm giriş/çıkış kayıtları", self.header_actions)
        )

        filters = QHBoxLayout()
        filters.setSpacing(8)
        today = date.today()
        self.start = QDateEdit(_qdate(today - timedelta(days=6)))
        self.end = QDateEdit(_qdate(today))
        for edit in (self.start, self.end):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("dd.MM.yyyy")
        filters.addWidget(QLabel("Tarih"))
        filters.addWidget(self.start)
        filters.addWidget(QLabel("–"))
        filters.addWidget(self.end)
        for label, days in (("Bugün", 0), ("7 gün", 6), ("30 gün", 29)):
            quick = QPushButton(label)
            quick.clicked.connect(lambda _=False, d=days: self._quick_range(d))
            filters.addWidget(quick)

        self.plate = QLineEdit()
        self.plate.setPlaceholderText("Plaka")
        self.plate.addAction(icon("mdi6.magnify"), QLineEdit.ActionPosition.LeadingPosition)
        self.plate.setClearButtonEnabled(True)
        self.plate.setMaximumWidth(170)
        filters.addWidget(self.plate)

        self.vehicle_type = QComboBox()
        self.vehicle_type.addItem("Tüm araçlar", None)
        for vtype in VehicleType:
            self.vehicle_type.addItem(icon(vtype.icon, vtype.color), vtype.label, vtype)
        filters.addWidget(self.vehicle_type)

        self.status = QComboBox()
        self.status.addItem("Tüm durumlar", None)
        for status in SessionStatus:
            self.status.addItem(status.label, status)
        filters.addWidget(self.status)

        self.unpaid = QCheckBox("Ödenmemiş")
        filters.addWidget(self.unpaid)
        filters.addStretch(1)
        root.addLayout(filters)

        status_colors = {
            SessionStatus.OPEN: palette.success,
            SessionStatus.CLOSED: palette.muted,
            SessionStatus.EXIT_MISSED: palette.warning,
        }
        columns = [
            Column("Plaka", lambda s: s.plate),
            Column(
                "Araç tipi",
                lambda s: s.vehicle_type.label,
                icon=lambda s: icon(s.vehicle_type.icon, s.vehicle_type.color),
                width=160,
            ),
            Column(
                "Giriş",
                lambda s: format_datetime(s.entry_time),
                sort=lambda s: s.entry_time,
                width=140,
            ),
            Column(
                "Çıkış",
                lambda s: format_datetime(s.exit_time),
                sort=lambda s: s.exit_time,
                width=140,
            ),
            Column(
                "Süre",
                lambda s: format_duration(s.duration()),
                sort=lambda s: s.duration(),
                width=120,
            ),
            Column(
                "Ücret",
                lambda s: "" if s.fee is None else format_money(s.fee, currency),
                sort=lambda s: s.fee or Decimal(0),
                align=RIGHT,
                width=110,
            ),
            Column(
                "Ödeme",
                self._payment_text,
                color=lambda s: palette.danger if self._unpaid(s) else None,
                width=110,
            ),
            Column(
                "Durum",
                lambda s: s.status.label,
                color=lambda s: status_colors[s.status],
                width=120,
            ),
            Column("Kameralar", self._cameras),
        ]
        self.model = RowModel(columns, alert=lambda s: bool(s.vehicle and s.vehicle.is_blacklisted))
        self.table = DataTable(self.model)
        self.table.doubleClicked.connect(
            lambda index: controller.show_session(self.table.row_for_index(index).id)
        )
        root.addWidget(self.table, 1)
        self.summary = muted("")
        root.addWidget(self.summary)

        # Filtre değişince kısa bir gecikmeyle yenile (yazarken her tuşta sorgu atılmasın)
        self._debounce = QTimer(self, singleShot=True, interval=250)
        self._debounce.timeout.connect(self.reload)
        for signal in (
            self.start.dateChanged,
            self.end.dateChanged,
            self.plate.textChanged,
            self.vehicle_type.currentIndexChanged,
            self.status.currentIndexChanged,
            self.unpaid.toggled,
        ):
            signal.connect(lambda *_: self._debounce.start())
        controller.data_changed.connect(self.reload)
        controller.result_added.connect(lambda _r: self._debounce.start())
        self.reload()

    @staticmethod
    def _unpaid(session: ParkingSession) -> bool:
        return session.status is SessionStatus.CLOSED and not session.is_paid and bool(session.fee)

    def _payment_text(self, session: ParkingSession) -> str:
        if session.payment_method is not None:
            return session.payment_method.label
        return "Ödenmedi" if self._unpaid(session) else ""

    @staticmethod
    def _cameras(session: ParkingSession) -> str:
        parts = [session.entry_camera + (" (m)" if session.is_manual_entry else "")]
        if session.exit_camera:
            parts.append(session.exit_camera + (" (m)" if session.is_manual_exit else ""))
        return " → ".join(parts)

    def _quick_range(self, days: int) -> None:
        today = date.today()
        self.start.setDate(_qdate(today - timedelta(days=days)))
        self.end.setDate(_qdate(today))

    def filters(self) -> dict:
        start = datetime.combine(self.start.date().toPython(), time.min)
        end = datetime.combine(self.end.date().toPython(), time.min) + timedelta(days=1)
        return {
            "start": start,
            "end": end,
            "plate": self.plate.text(),
            "vehicle_type": enum_data(self.vehicle_type, VehicleType),
            "status": enum_data(self.status, SessionStatus),
            "unpaid_only": self.unpaid.isChecked(),
        }

    def reload(self) -> None:
        sessions = self.ctx.parking.find_sessions(**self.filters(), limit=MAX_ROWS)
        self.model.set_rows(sessions)
        currency = self.ctx.config.parking.currency
        total = sum((s.fee or Decimal(0)) for s in sessions)
        paid = sum((s.fee or Decimal(0)) for s in sessions if s.is_paid)
        inside = sum(1 for s in sessions if s.is_open)
        limit_note = f" (ilk {MAX_ROWS} kayıt)" if len(sessions) >= MAX_ROWS else ""
        self.summary.setText(
            f"{len(sessions)} kayıt{limit_note} · {inside} içeride · toplam ücret "
            f"{format_money(total, currency)} · tahsil edilen {format_money(paid, currency)}"
        )

    def _detail_selected(self) -> None:
        session = self.table.selected_row()
        if session is not None:
            self.controller.show_session(session.id)

    def _pay_selected(self) -> None:
        session = self.table.selected_row()
        if session is not None and self._unpaid(session):
            self.controller.collect_payment(session.id)
