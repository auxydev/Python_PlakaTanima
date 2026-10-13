"""Araç tipine göre ücret tarifeleri ve örnek hesaplayıcı."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from plakatanima.core.formatting import format_money
from plakatanima.core.pricing import TariffRule
from plakatanima.core.vehicle import VehicleType
from plakatanima.gui.controller import Controller
from plakatanima.gui.utils import (
    Card,
    button,
    enum_data,
    icon,
    muted,
    page_header,
    section_title,
)


def _money_box(currency: str) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(0, 100_000)
    box.setDecimals(2)
    box.setSingleStep(5)
    box.setSuffix(f" {currency}")
    box.setAlignment(Qt.AlignmentFlag.AlignRight)
    box.setMinimumWidth(130)
    return box


class _TariffRow:
    def __init__(self, vehicle_type: VehicleType, currency: str) -> None:
        self.vehicle_type = vehicle_type
        self.free = QSpinBox()
        self.free.setRange(0, 24 * 60)
        self.free.setSuffix(" dk")
        self.free.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.free.setMinimumWidth(110)
        self.first = _money_box(currency)
        self.extra = _money_box(currency)
        self.daily = _money_box(currency)
        self.daily.setSpecialValueText("Yok")

    def load(self, rule: TariffRule) -> None:
        self.free.setValue(rule.free_minutes)
        self.first.setValue(float(rule.first_hour_fee))
        self.extra.setValue(float(rule.additional_hour_fee))
        self.daily.setValue(float(rule.daily_max_fee))

    def rule(self) -> TariffRule:
        def dec(box: QDoubleSpinBox) -> Decimal:
            return Decimal(str(round(box.value(), 2)))

        return TariffRule(self.free.value(), dec(self.first), dec(self.extra), dec(self.daily))


class TariffsPage(QWidget):
    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageRoot")
        self.controller = controller
        self.ctx = controller.ctx
        currency = self.ctx.config.parking.currency

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)
        save = button("Kaydet", "mdi6.content-save-outline", variant="primary")
        save.clicked.connect(self.save)
        revert = button("Geri Al", "mdi6.undo")
        revert.clicked.connect(self.reload)
        root.addWidget(
            page_header("Tarifeler", "Araç tipine göre otopark ücretleri", [revert, save])
        )

        card = Card()
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        headers = ("Araç tipi", "Ücretsiz süre", "İlk saat", "Sonraki her saat", "Günlük tavan")
        for col, text in enumerate(headers):
            label = QLabel(text.upper())
            label.setObjectName("CardTitle")
            grid.addWidget(label, 0, col)
        self.rows: dict[VehicleType, _TariffRow] = {}
        for r, vtype in enumerate(VehicleType, start=1):
            name = QHBoxLayout()
            ico = QLabel()
            ico.setPixmap(icon(vtype.icon, vtype.color).pixmap(22, 22))
            name.addWidget(ico)
            name.addWidget(QLabel(f"<b>{vtype.label}</b>"))
            name.addStretch(1)
            grid.addLayout(name, r, 0)
            row = _TariffRow(vtype, currency)
            for col, widget in enumerate((row.free, row.first, row.extra, row.daily), start=1):
                grid.addWidget(widget, r, col)
                widget.valueChanged.connect(self._update_example)
            self.rows[vtype] = row
        grid.setColumnStretch(5, 1)
        card.body.addLayout(grid)
        card.body.addWidget(
            muted(
                "Kalış süresi ücretsiz süreyi aşarsa ilk saat ücreti, sonraki her başlayan saat "
                "için ek saat ücreti alınır. Her 24 saatlik dilim günlük tavanı aşamaz."
            )
        )
        root.addWidget(card)

        calc = Card()
        calc.body.addWidget(section_title("Ücret hesaplayıcı"))
        row = QHBoxLayout()
        self.calc_type = QComboBox()
        for vtype in VehicleType:
            self.calc_type.addItem(icon(vtype.icon, vtype.color), vtype.label, vtype)
        self.calc_hours = QSpinBox()
        self.calc_hours.setRange(0, 24 * 30)
        self.calc_hours.setSuffix(" sa")
        self.calc_hours.setValue(2)
        self.calc_minutes = QSpinBox()
        self.calc_minutes.setRange(0, 59)
        self.calc_minutes.setSuffix(" dk")
        self.calc_minutes.setValue(30)
        self.calc_result = QLabel("")
        self.calc_result.setObjectName("CardValue")
        for widget in (self.calc_type, self.calc_hours, self.calc_minutes):
            row.addWidget(widget)
        row.addSpacing(20)
        row.addWidget(self.calc_result)
        row.addStretch(1)
        self.calc_type.currentIndexChanged.connect(self._update_example)
        self.calc_hours.valueChanged.connect(self._update_example)
        self.calc_minutes.valueChanged.connect(self._update_example)
        calc.body.addLayout(row)
        root.addWidget(calc)
        root.addStretch(1)
        self.reload()

    def reload(self) -> None:
        for tariff in self.ctx.tariffs.all():
            row = self.rows.get(tariff.vehicle_type)
            if row is not None:
                row.load(tariff.to_rule())
        self._update_example()

    def save(self) -> None:
        for vtype, row in self.rows.items():
            rule = row.rule()
            self.ctx.tariffs.update(
                vtype,
                free_minutes=rule.free_minutes,
                first_hour_fee=rule.first_hour_fee,
                additional_hour_fee=rule.additional_hour_fee,
                daily_max_fee=rule.daily_max_fee,
            )
        self.controller.toast(
            "Tarifeler kaydedildi", "Yeni ücretler sonraki çıkışlarda geçerli.", "success"
        )
        self.controller.data_changed.emit()

    def _update_example(self) -> None:
        vtype = enum_data(self.calc_type, VehicleType)
        rule = self.rows[vtype].rule()
        minutes = self.calc_hours.value() * 60 + self.calc_minutes.value()
        fee = rule.fee_for_minutes(minutes)
        self.calc_result.setText(format_money(fee, self.ctx.config.parking.currency))
