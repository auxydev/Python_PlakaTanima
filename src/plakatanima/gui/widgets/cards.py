"""Gösterge paneli kartları."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QWidget

from plakatanima.core.vehicle import VehicleType
from plakatanima.gui import theme
from plakatanima.gui.utils import Card, chip_color, icon, set_variant


def _icon_badge(icon_name: str, color: str, size: int = 38) -> QLabel:
    badge = QLabel()
    badge.setFixedSize(size, size)
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    badge.setPixmap(icon(icon_name, color).pixmap(size // 2, size // 2))
    badge.setStyleSheet(f"background:{chip_color(color, 45)}; border-radius:{size // 2 - 4}px;")
    return badge


class StatCard(Card):
    def __init__(self, title: str, icon_name: str, color: str, parent: QWidget | None = None):
        super().__init__(parent)
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(_icon_badge(icon_name, color))
        self.title = QLabel(title.upper())
        self.title.setObjectName("CardTitle")
        top.addWidget(self.title, 1)
        self.body.addLayout(top)
        self.value = QLabel("—")
        self.value.setObjectName("CardValue")
        self.body.addWidget(self.value)
        self.hint = QLabel("")
        self.hint.setObjectName("CardHint")
        self.body.addWidget(self.hint)

    def set_value(self, value: str, hint: str = "") -> None:
        self.value.setText(value)
        self.hint.setText(hint)


class OccupancyCard(Card):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        palette = theme.current()
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(_icon_badge("mdi6.parking", palette.accent))
        title = QLabel("DOLULUK")
        title.setObjectName("CardTitle")
        top.addWidget(title, 1)
        self.percent = QLabel("")
        self.percent.setObjectName("CardHint")
        top.addWidget(self.percent)
        self.body.addLayout(top)

        self.value = QLabel("—")
        self.value.setObjectName("CardValue")
        self.body.addWidget(self.value)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.body.addWidget(self.bar)

        self.types = QHBoxLayout()
        self.types.setSpacing(12)
        self._type_labels: dict[VehicleType, QLabel] = {}
        for vtype in VehicleType:
            if vtype is VehicleType.UNKNOWN:
                continue
            item = QHBoxLayout()
            item.setSpacing(3)
            ico = QLabel()
            ico.setPixmap(icon(vtype.icon, vtype.color).pixmap(16, 16))
            ico.setToolTip(vtype.label)
            count = QLabel("0")
            count.setObjectName("CardHint")
            count.setToolTip(vtype.label)
            item.addWidget(ico)
            item.addWidget(count)
            self.types.addLayout(item)
            self._type_labels[vtype] = count
        self.types.addStretch(1)
        self.body.addLayout(self.types)

    def set_values(self, inside: int, capacity: int, by_type: dict[VehicleType, int]) -> None:
        ratio = inside / capacity if capacity else 0
        self.value.setText(f"{inside} / {capacity}")
        self.percent.setText(f"%{ratio * 100:.0f} · {max(capacity - inside, 0)} boş")
        self.bar.setRange(0, max(capacity, 1))
        self.bar.setValue(min(inside, capacity))
        level = "danger" if ratio >= 0.95 else "warning" if ratio >= 0.8 else None
        set_variant(self.bar, level, prop="level")
        for vtype, label in self._type_labels.items():
            count = by_type.get(vtype, 0)
            if vtype is VehicleType.CAR:
                count += by_type.get(VehicleType.UNKNOWN, 0)
            label.setText(str(count))
