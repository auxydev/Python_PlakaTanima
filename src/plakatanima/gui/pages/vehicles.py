"""Kayıtlı araçlar: aboneler, kara liste, sahip bilgileri."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from plakatanima.core.formatting import format_datetime
from plakatanima.db.models import Vehicle
from plakatanima.gui import theme
from plakatanima.gui.controller import Controller
from plakatanima.gui.dialogs import VehicleDialog
from plakatanima.gui.utils import button, confirm, icon, muted, page_header, show_error
from plakatanima.gui.widgets.table import Column, DataTable, RowModel


def _subscription(vehicle: Vehicle) -> str:
    if not vehicle.is_subscriber:
        return ""
    if vehicle.subscription_end is None:
        return "Süresiz"
    text = vehicle.subscription_end.strftime("%d.%m.%Y")
    return text if vehicle.has_active_subscription() else f"{text} (bitti)"


class VehiclesPage(QWidget):
    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageRoot")
        self.controller = controller
        self.ctx = controller.ctx
        palette = theme.current()

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)
        add = button("Yeni Araç", "mdi6.plus", variant="primary")
        add.clicked.connect(self._add)
        edit = button("Düzenle", "mdi6.pencil-outline")
        edit.clicked.connect(self._edit_selected)
        delete = button("Sil", "mdi6.delete-outline", variant="danger")
        delete.clicked.connect(self._delete_selected)
        root.addWidget(
            page_header(
                "Araçlar",
                "Abone ve kara liste araçları, sahip bilgileri",
                [add, edit, delete],
            )
        )

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Plaka, sahip, telefon veya model ara…")
        self.search.addAction(icon("mdi6.magnify"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(360)
        bar.addWidget(self.search)
        self.filter_group = QButtonGroup(self)
        for i, label in enumerate(("Tümü", "Aboneler", "Kara liste")):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            self.filter_group.addButton(btn, i)
            bar.addWidget(btn)
        bar.addStretch(1)
        self.summary = muted("")
        bar.addWidget(self.summary)
        root.addLayout(bar)

        columns = [
            Column("Plaka", lambda v: v.plate),
            Column(
                "Araç tipi",
                lambda v: v.vehicle_type.label,
                icon=lambda v: icon(v.vehicle_type.icon, v.vehicle_type.color),
                width=160,
            ),
            Column("Sahibi / Firma", lambda v: v.owner_name, width=180),
            Column("Telefon", lambda v: v.phone, width=130),
            Column(
                "Marka / Model",
                lambda v: " ".join(x for x in (v.brand_model, v.color) if x),
                width=170,
            ),
            Column(
                "Abonelik",
                _subscription,
                sort=lambda v: v.subscription_end or date.max if v.is_subscriber else date.min,
                color=lambda v: palette.success if v.has_active_subscription() else None,
                width=120,
            ),
            Column(
                "Kara liste",
                lambda v: (v.blacklist_reason or "Evet") if v.is_blacklisted else "",
                color=lambda v: palette.danger if v.is_blacklisted else None,
                width=150,
            ),
            Column(
                "Eklenme",
                lambda v: format_datetime(v.created_at),
                sort=lambda v: v.created_at,
                width=130,
            ),
            Column("Not", lambda v: v.notes.replace("\n", " ")),
        ]
        self.model = RowModel(columns, alert=lambda v: v.is_blacklisted)
        self.table = DataTable(self.model)
        self.table.doubleClicked.connect(lambda index: self._edit(self.table.row_for_index(index)))
        root.addWidget(self.table, 1)

        self._debounce = QTimer(self, singleShot=True, interval=200)
        self._debounce.timeout.connect(self.reload)
        self.search.textChanged.connect(lambda *_: self._debounce.start())
        self.filter_group.idToggled.connect(lambda _id, on: on and self.reload())
        controller.data_changed.connect(self.reload)
        self.reload()

    def reload(self) -> None:
        mode = self.filter_group.checkedId()
        vehicles = self.ctx.vehicles.search(
            self.search.text(), subscribers_only=mode == 1, blacklisted_only=mode == 2
        )
        self.model.set_rows(vehicles)
        subscribers = sum(1 for v in vehicles if v.has_active_subscription())
        blacklisted = sum(1 for v in vehicles if v.is_blacklisted)
        self.summary.setText(
            f"{len(vehicles)} araç · {subscribers} aktif abone · {blacklisted} kara listede"
        )

    def _add(self) -> None:
        dialog = VehicleDialog(parent=self)
        if dialog.exec() and dialog.data is not None:
            self._save(dialog.data, None)

    def _edit(self, vehicle: Vehicle) -> None:
        dialog = VehicleDialog(vehicle, parent=self)
        if dialog.exec() and dialog.data is not None:
            self._save(dialog.data, vehicle.id)

    def _save(self, data, vehicle_id: int | None) -> None:
        try:
            self.ctx.vehicles.save(data, vehicle_id)
        except (ValueError, LookupError) as exc:
            show_error(self, str(exc))
            return
        self.controller.data_changed.emit()

    def _edit_selected(self) -> None:
        vehicle = self.table.selected_row()
        if vehicle is not None:
            self._edit(vehicle)

    def _delete_selected(self) -> None:
        vehicle = self.table.selected_row()
        if vehicle is None:
            return
        if confirm(self, "Aracı sil", f"{vehicle.plate} kaydı silinsin mi? Geçiş geçmişi korunur."):
            self.ctx.vehicles.delete(vehicle.id)
            self.controller.data_changed.emit()
