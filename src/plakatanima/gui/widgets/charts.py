"""Hafif grafik bileşenleri (QPainter).

Kurallar: ince sütunlar (en çok 24 px, veri ucunda 4 px yuvarlatma, tabanda düz),
silik tek piksellik ızgara, iki ve daha fazla seride lejant, metinler veri rengini
değil metin tonunu kullanır, ayrıntı üzerine gelince ipucunda gösterilir.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from plakatanima.core.vehicle import VehicleType
from plakatanima.gui import theme

# Doğrulanmış kategorik palet (validate_palette.js ile koyu ve açık yüzeyde test edildi)
SERIES_DARK = ("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9")
SERIES_LIGHT = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6")

_VEHICLE_SLOT = {
    VehicleType.CAR: 0,
    VehicleType.MOTORCYCLE: 1,
    VehicleType.LIGHT_COMMERCIAL: 2,
    VehicleType.TRUCK: 3,
    VehicleType.BUS: 4,
}

BAR_MAX = 24
RADIUS = 4
GAP = 2


def series_color(slot: int) -> str:
    colors = SERIES_LIGHT if theme.current().name == "light" else SERIES_DARK
    return colors[slot % len(colors)]


def vehicle_color(vehicle_type: VehicleType) -> str:
    slot = _VEHICLE_SLOT.get(vehicle_type)
    return theme.current().muted if slot is None else series_color(slot)


def entry_color() -> str:
    return series_color(2)


def exit_color() -> str:
    return series_color(0)


def nice_ceiling(value: float, ticks: int = 4) -> tuple[float, float]:
    """Eksen için yuvarlak üst sınır ve adım."""
    if value <= 0:
        return 1.0, 0.25
    raw = value / ticks
    magnitude = 10 ** math.floor(math.log10(raw))
    for factor in (1, 2, 2.5, 5, 10):
        step = factor * magnitude
        if step * ticks >= value:
            return step * ticks, step
    return 10 * magnitude * ticks, 10 * magnitude


def compact(value: float) -> str:
    """0 / 950 / 1,2B / 3,4M (Türkçe kısaltma: bin, milyon)."""
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M".replace(".0M", "M").replace(".", ",")
    if abs(value) >= 1000:
        return f"{value / 1000:.1f}B".replace(".0B", "B").replace(".", ",")
    return f"{value:.0f}" if float(value).is_integer() else f"{value:.1f}".replace(".", ",")


def _rounded_column(x: float, top: float, width: float, base: float) -> QPainterPath:
    """Üstü yuvarlatılmış, tabanı düz sütun."""
    radius = min(RADIUS, width / 2, max(base - top, 0))
    path = QPainterPath()
    path.moveTo(x, base)
    path.lineTo(x, top + radius)
    path.quadTo(x, top, x + radius, top)
    path.lineTo(x + width - radius, top)
    path.quadTo(x + width, top, x + width, top + radius)
    path.lineTo(x + width, base)
    path.closeSubpath()
    return path


def _rounded_bar(x: float, y: float, length: float, thickness: float) -> QPainterPath:
    """Sağ ucu yuvarlatılmış yatay çubuk."""
    radius = min(RADIUS, thickness / 2, length)
    right = x + length
    path = QPainterPath()
    path.moveTo(x, y)
    path.lineTo(right - radius, y)
    path.quadTo(right, y, right, y + radius)
    path.lineTo(right, y + thickness - radius)
    path.quadTo(right, y + thickness, right - radius, y + thickness)
    path.lineTo(x, y + thickness)
    path.closeSubpath()
    return path


@dataclass(slots=True)
class Series:
    name: str
    color: str
    values: Sequence[float]


class ColumnChart(QWidget):
    """Gruplu sütun grafiği (ör. saatlik giriş/çıkış)."""

    def __init__(
        self,
        value_format: Callable[[float], str] = compact,
        empty_text: str = "Bu dönem için veri yok",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(170)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.value_format = value_format
        self.empty_text = empty_text
        self._categories: list[str] = []
        self._tooltips: list[str] = []
        self._series: list[Series] = []
        self._hover: int | None = None
        self._plot = QRectF()

    def sizeHint(self) -> QSize:
        return QSize(480, 220)

    def set_data(
        self,
        categories: Sequence[str],
        series: Sequence[Series],
        tooltips: Sequence[str] | None = None,
    ) -> None:
        self._categories = list(categories)
        self._series = list(series)
        self._tooltips = list(tooltips) if tooltips else list(categories)
        self._hover = None
        self.update()

    def _max_value(self) -> float:
        return max((max(s.values, default=0) for s in self._series), default=0)

    def paintEvent(self, _event) -> None:
        palette = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        font.setPointSizeF(max(font.pointSizeF() - 1.5, 7.5))
        painter.setFont(font)
        metrics = painter.fontMetrics()
        muted, text = QColor(palette.muted), QColor(palette.text)

        if not self._categories or self._max_value() <= 0:
            painter.setPen(muted)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.empty_text)
            painter.end()
            return

        top = 6.0
        if len(self._series) >= 2:  # lejant
            x = 0.0
            for series in self._series:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(series.color))
                painter.drawRoundedRect(QRectF(x, 5, 10, 10), 2, 2)
                painter.setPen(text)
                painter.drawText(QPointF(x + 15, 14), series.name)
                x += 15 + metrics.horizontalAdvance(series.name) + 18
            top = 26.0

        max_value, step = nice_ceiling(self._max_value())
        ticks = [step * i for i in range(round(max_value / step) + 1)]
        label_w = max(metrics.horizontalAdvance(self.value_format(t)) for t in ticks) + 8
        plot = QRectF(label_w, top + 4, self.width() - label_w - 4, self.height() - top - 26)
        self._plot = plot

        grid = QColor(palette.border)
        grid.setAlpha(150)
        for tick in ticks:
            y = plot.bottom() - tick / max_value * plot.height()
            painter.setPen(QPen(grid if tick else QColor(palette.border), 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(muted)
            painter.drawText(
                QRectF(0, y - 8, label_w - 6, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                self.value_format(tick),
            )

        count = len(self._categories)
        band = plot.width() / count
        if self._hover is not None:
            highlight = QColor(palette.text)
            highlight.setAlpha(14)
            painter.fillRect(
                QRectF(plot.left() + self._hover * band, plot.top(), band, plot.height()), highlight
            )

        n = len(self._series)
        bar_w = max(min(BAR_MAX, (band * 0.72 - GAP * (n - 1)) / n), 2)
        group_w = bar_w * n + GAP * (n - 1)
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(count):
            x0 = plot.left() + i * band + (band - group_w) / 2
            for j, series in enumerate(self._series):
                value = series.values[i] if i < len(series.values) else 0
                if value <= 0:
                    continue
                height = value / max_value * plot.height()
                painter.setBrush(QColor(series.color))
                painter.drawPath(
                    _rounded_column(
                        x0 + j * (bar_w + GAP), plot.bottom() - height, bar_w, plot.bottom()
                    )
                )

        # X ekseni etiketleri: çakışmasın diye gerektiği kadar atlanır
        widest = max(metrics.horizontalAdvance(c) for c in self._categories) + 8
        every = max(1, math.ceil(widest / band))
        painter.setPen(muted)
        for i, category in enumerate(self._categories):
            if i % every:
                continue
            painter.drawText(
                QRectF(
                    plot.left() + i * band - widest / 2 + band / 2, plot.bottom() + 4, widest, 18
                ),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                category,
            )
        painter.end()

    def mouseMoveEvent(self, event) -> None:
        plot = self._plot
        pos = event.position()
        if not self._categories or not plot.contains(pos):
            self._set_hover(None)
            QToolTip.hideText()
            return
        index = min(
            int((pos.x() - plot.left()) / (plot.width() / len(self._categories))),
            len(self._categories) - 1,
        )
        self._set_hover(index)
        rows = "".join(
            f"<tr><td><span style='color:{s.color}'>■</span> {s.name}</td>"
            f"<td align='right'>&nbsp;&nbsp;<b>{self.value_format(s.values[index])}</b></td></tr>"
            for s in self._series
        )
        QToolTip.showText(
            event.globalPosition().toPoint(),
            f"<b>{self._tooltips[index]}</b><table>{rows}</table>",
            self,
        )

    def leaveEvent(self, _event) -> None:
        self._set_hover(None)

    def _set_hover(self, index: int | None) -> None:
        if index != self._hover:
            self._hover = index
            self.update()


@dataclass(slots=True)
class BarItem:
    label: str
    value: float
    color: str
    text: str = ""


class BarListChart(QWidget):
    """Yatay çubuk listesi: etiket, çubuk ve uçta değer (ör. araç tipi dağılımı)."""

    ROW = 30
    THICKNESS = 14

    def __init__(self, empty_text: str = "Veri yok", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.empty_text = empty_text
        self._items: list[BarItem] = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def set_items(self, items: Sequence[BarItem]) -> None:
        self._items = list(items)
        self.setMinimumHeight(max(len(self._items), 1) * self.ROW + 6)
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(320, max(len(self._items), 1) * self.ROW + 6)

    def paintEvent(self, _event) -> None:
        palette = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        metrics = painter.fontMetrics()
        if not self._items or max(i.value for i in self._items) <= 0:
            painter.setPen(QColor(palette.muted))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.empty_text)
            painter.end()
            return
        label_w = max(metrics.horizontalAdvance(i.label) for i in self._items) + 12
        value_w = max(metrics.horizontalAdvance(i.text or compact(i.value)) for i in self._items)
        track = max(self.width() - label_w - value_w - 12, 10)
        top_value = max(i.value for i in self._items)
        for row, item in enumerate(self._items):
            y = row * self.ROW + 4
            painter.setPen(QColor(palette.text))
            painter.drawText(
                QRectF(0, y, label_w - 8, self.ROW - 8),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                item.label,
            )
            length = item.value / top_value * track if item.value > 0 else 0
            bar_y = y + (self.ROW - 8 - self.THICKNESS) / 2
            if length > 0:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(item.color))
                painter.drawPath(_rounded_bar(label_w, bar_y, max(length, 2), self.THICKNESS))
            painter.setPen(QColor(palette.muted))
            painter.drawText(
                QRectF(label_w + length + 6, y, value_w + 6, self.ROW - 8),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                item.text or compact(item.value),
            )
        painter.end()

    def mouseMoveEvent(self, event) -> None:
        row = int((event.position().y() - 4) // self.ROW)
        if not 0 <= row < len(self._items):
            QToolTip.hideText()
            return
        item = self._items[row]
        total = sum(i.value for i in self._items) or 1
        QToolTip.showText(
            event.globalPosition().toPoint(),
            f"<b>{item.label}</b><br>{item.text or compact(item.value)}"
            f" · %{item.value / total * 100:.0f}",
            self,
        )
