"""İçerideki araçlar: anlık süre ve biriken ücret, manuel çıkış."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from plakatanima.core.formatting import format_datetime, format_duration, format_money
from plakatanima.core.plate import clean_text
from plakatanima.db.models import ParkingSession
from plakatanima.gui import theme
from plakatanima.gui.controller import Controller
from plakatanima.gui.utils import button, icon, muted, page_header
from plakatanima.gui.widgets.table import RIGHT, Column, DataTable, RowModel


class InsidePage(QWidget):
    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageRoot")
        self.controller = controller
        self.ctx = controller.ctx
        self._fees: dict[int, object] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        exit_btn = button("Çıkış Yap", "mdi6.logout", variant="primary")
        exit_btn.clicked.connect(self._exit_selected)
        detail_btn = button("Ayrıntı", "mdi6.image-search-outline")
        detail_btn.clicked.connect(self._detail_selected)
        refresh = button("Yenile", "mdi6.refresh")
        refresh.clicked.connect(self.reload)
        root.addWidget(
            page_header(
                "İçerideki Araçlar",
                "Otoparkta bulunan araçlar, kalış süresi ve biriken ücret",
                [detail_btn, exit_btn, refresh],
            )
        )

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Plaka ara…")
        self.search.addAction(icon("mdi6.magnify"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(280)
        self.search.textChanged.connect(self._apply_filter)
        bar.addWidget(self.search)
        bar.addStretch(1)
        self.summary = muted("")
        bar.addWidget(self.summary)
        root.addLayout(bar)

        palette = theme.current()
        currency = self.ctx.config.parking.currency
        columns = [
            Column("Plaka", lambda s: s.plate),
            Column(
                "Araç tipi",
                lambda s: s.vehicle_type.label,
                icon=lambda s: icon(s.vehicle_type.icon, s.vehicle_type.color),
                width=170,
            ),
            Column(
                "Giriş",
                lambda s: format_datetime(s.entry_time),
                sort=lambda s: s.entry_time,
                width=150,
            ),
            Column(
                "Süre",
                lambda s: format_duration(s.duration()),
                sort=lambda s: s.duration(),
                width=130,
            ),
            Column(
                "Biriken ücret",
                lambda s: format_money(self._fees.get(s.id, 0), currency),
                sort=lambda s: self._fees.get(s.id, 0),
                align=RIGHT,
                width=130,
            ),
            Column(
                "Kamera",
                lambda s: s.entry_camera + (" (manuel)" if s.is_manual_entry else ""),
                width=160,
            ),
            Column("Not", self._note, color=lambda s: self._note_color(s, palette)),
        ]
        self.model = RowModel(columns, alert=lambda s: bool(s.vehicle and s.vehicle.is_blacklisted))
        self.table = DataTable(self.model)
        self.table.doubleClicked.connect(
            lambda index: controller.show_session(self.table.row_for_index(index).id)
        )
        root.addWidget(self.table, 1)

        controller.result_added.connect(lambda _r: self.reload())
        controller.data_changed.connect(self.reload)
        self._timer = QTimer(self, interval=30_000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self.reload()

    @staticmethod
    def _note(session: ParkingSession) -> str:
        vehicle = session.vehicle
        if vehicle is None:
            return ""
        if vehicle.is_blacklisted:
            return "KARA LİSTE" + (
                f": {vehicle.blacklist_reason}" if vehicle.blacklist_reason else ""
            )
        if vehicle.has_active_subscription():
            return "Abone" + (f" · {vehicle.owner_name}" if vehicle.owner_name else "")
        return vehicle.owner_name

    @staticmethod
    def _note_color(session: ParkingSession, palette) -> str | None:
        vehicle = session.vehicle
        if vehicle is not None and vehicle.is_blacklisted:
            return palette.danger
        if vehicle is not None and vehicle.has_active_subscription():
            return palette.success
        return None

    def reload(self) -> None:
        sessions = self.ctx.parking.open_sessions()
        self._compute_fees(sessions)
        self.model.set_rows(sessions)
        self._apply_filter()

    def _compute_fees(self, sessions: list[ParkingSession]) -> None:
        now = datetime.now()
        rules = {}
        fees = {}
        for session in sessions:
            vehicle = session.vehicle
            if vehicle is not None and vehicle.has_active_subscription(now.date()):
                fees[session.id] = 0
                continue
            rule = rules.get(session.vehicle_type)
            if rule is None:
                rule = rules[session.vehicle_type] = self.ctx.parking.tariff_rule(
                    session.vehicle_type
                )
            fees[session.id] = rule.fee_between(session.entry_time, now)
        self._fees = fees

    def _tick(self) -> None:
        self._compute_fees(self.model.rows())
        self.model.refresh()
        self._update_summary()

    def _apply_filter(self) -> None:
        text = clean_text(self.search.text())
        for row in range(self.model.rowCount()):
            source_row = self.table.proxy.mapFromSource(self.model.index(row, 0)).row()
            hidden = bool(text) and text not in self.model.row_at(row).plate
            self.table.setRowHidden(source_row, hidden)
        self._update_summary()

    def _update_summary(self) -> None:
        total = sum(self._fees.values())
        count = self.model.rowCount()
        capacity = self.ctx.config.parking.capacity
        self.summary.setText(
            f"{count} araç · kapasite {capacity} · biriken toplam "
            f"{format_money(total, self.ctx.config.parking.currency)}"
        )

    def _exit_selected(self) -> None:
        session = self.table.selected_row()
        if session is not None:
            self.controller.exit_session(session.id)

    def _detail_selected(self) -> None:
        session = self.table.selected_row()
        if session is not None:
            self.controller.show_session(session.id)
