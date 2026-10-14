"""Son geçişler akışı."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from plakatanima.core.vehicle import VehicleType
from plakatanima.db.models import DetectionEvent, EventAction
from plakatanima.gui import theme
from plakatanima.gui.utils import chip_color, icon
from plakatanima.gui.widgets.elided import ElidedLabel
from plakatanima.gui.widgets.plate import PlateLabel
from plakatanima.services.parking import ParkingResult


@dataclass(slots=True)
class FeedEntry:
    timestamp: datetime
    plate: str
    action: EventAction
    vehicle_type: VehicleType
    camera: str
    detail: str
    blacklisted: bool = False
    session_id: int | None = None

    @classmethod
    def from_result(cls, result: ParkingResult) -> FeedEntry:
        return cls(
            timestamp=result.timestamp,
            plate=result.plate,
            action=result.action,
            vehicle_type=result.vehicle_type,
            camera=result.camera_name,
            detail=_detail(result.message),
            blacklisted=result.is_blacklisted,
            session_id=result.session_id,
        )

    @classmethod
    def from_event(cls, event: DetectionEvent) -> FeedEntry:
        return cls(
            timestamp=event.timestamp,
            plate=event.plate,
            action=event.action,
            vehicle_type=event.vehicle_type,
            camera=event.camera_name,
            detail=_detail(event.message),
            blacklisted=event.is_blacklisted,
            session_id=event.session_id,
        )


def _detail(message: str) -> str:
    # "Çıkış: 34 ABC 123 — Otomobil — 2 sa 05 dk — 120,00 TL" -> "2 sa 05 dk — 120,00 TL"
    parts = message.split(" — ")
    return " — ".join(parts[2:])


def action_color(action: EventAction) -> str:
    palette = theme.current()
    return {
        EventAction.ENTRY: palette.success,
        EventAction.EXIT: palette.info,
        EventAction.UNMATCHED_EXIT: palette.warning,
        EventAction.DUPLICATE: palette.muted,
    }[action]


class FeedItem(QWidget):
    def __init__(self, entry: FeedEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        palette = theme.current()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        plate = PlateLabel(entry.plate, height=24)
        plate.set_plate(entry.plate, alert=entry.blacklisted)
        layout.addWidget(plate)

        texts = QVBoxLayout()
        texts.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(6)
        color = palette.danger if entry.blacklisted else action_color(entry.action)
        chip = QLabel("KARA LİSTE" if entry.blacklisted else entry.action.label)
        chip.setStyleSheet(
            f"background:{chip_color(color, 55)}; color:{color}; border-radius:5px;"
            "padding:1px 7px; font-weight:700; font-size:8.5pt;"
        )
        top.addWidget(chip)
        type_icon = QLabel()
        type_icon.setPixmap(icon(entry.vehicle_type.icon, entry.vehicle_type.color).pixmap(15, 15))
        top.addWidget(type_icon)
        type_label = ElidedLabel(entry.vehicle_type.label)
        type_label.setStyleSheet("font-size:9pt;")
        top.addWidget(type_label, 1)
        when = QLabel(entry.timestamp.strftime("%H:%M"))
        when.setToolTip(entry.timestamp.strftime("%d.%m.%Y %H:%M:%S"))
        when.setObjectName("Muted")
        top.addWidget(when)
        texts.addLayout(top)

        sub = " · ".join(x for x in (entry.camera, entry.detail) if x)
        bottom = ElidedLabel(sub)
        bottom.setObjectName("Muted")
        bottom.setStyleSheet("font-size:8.5pt;")
        texts.addWidget(bottom)
        layout.addLayout(texts, 1)


class EventFeed(QListWidget):
    session_activated = Signal(int)

    def __init__(self, limit: int = 50, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.limit = limit
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.setSpacing(2)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("QListWidget { border: none; background: transparent; }")
        self.itemDoubleClicked.connect(self._activated)

    def _activated(self, item: QListWidgetItem) -> None:
        session_id = item.data(Qt.ItemDataRole.UserRole)
        if session_id:
            self.session_activated.emit(int(session_id))

    def add_entry(self, entry: FeedEntry, *, top: bool = True) -> None:
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, entry.session_id)
        widget = FeedItem(entry)
        item.setSizeHint(QSize(100, max(widget.sizeHint().height(), 54)))
        if entry.blacklisted:
            item.setBackground(Qt.GlobalColor.transparent)
            widget.setStyleSheet(
                f"background:{chip_color(theme.current().danger, 28)}; border-radius:8px;"
            )
        if top:
            self.insertItem(0, item)
        else:
            self.addItem(item)
        self.setItemWidget(item, widget)
        while self.count() > self.limit:
            self.takeItem(self.count() - 1)

    def set_entries(self, entries: list[FeedEntry]) -> None:
        self.clear()
        for entry in entries:
            self.add_entry(entry, top=False)
