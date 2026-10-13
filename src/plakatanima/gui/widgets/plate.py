"""Türk plakası görünümünde etiket ve tablo hücresi çizimi."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QStyle, QStyledItemDelegate, QWidget

from plakatanima.core.plate import format_plate

PLATE_BLUE = QColor("#0038A8")
PLATE_BG = QColor("#F8F8F6")
PLATE_TEXT = QColor("#111111")
PLATE_BORDER = QColor("#1B1B1B")


def paint_plate(painter: QPainter, rect: QRectF, plate: str, *, alert: bool = False) -> None:
    """``rect`` içine plaka çizer (oran korunmaz; çağıran uygun dikdörtgen verir)."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    radius = rect.height() * 0.14
    border = QColor("#EF4444") if alert else PLATE_BORDER
    painter.setPen(QPen(border, 2 if alert else 1.2))
    painter.setBrush(PLATE_BG)
    painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

    strip = QRectF(rect.left() + 1.5, rect.top() + 1.5, rect.height() * 0.42, rect.height() - 3)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(PLATE_BLUE)
    painter.drawRoundedRect(strip, radius * 0.7, radius * 0.7)
    tr_font = QFont()
    tr_font.setBold(True)
    tr_font.setPixelSize(max(int(rect.height() * 0.26), 6))
    painter.setFont(tr_font)
    painter.setPen(QColor("#FFFFFF"))
    tr_rect = QRectF(
        strip.left(), strip.top() + strip.height() * 0.5, strip.width(), strip.height() * 0.45
    )
    painter.drawText(tr_rect, Qt.AlignmentFlag.AlignCenter, "TR")

    text_rect = QRectF(
        strip.right() + 2, rect.top(), rect.right() - strip.right() - 4, rect.height()
    )
    font = QFont()
    font.setBold(True)
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 104)
    size = rect.height() * 0.62
    label = format_plate(plate)
    while size > 6:
        font.setPixelSize(int(size))
        if QFontMetricsF(font).horizontalAdvance(label) <= text_rect.width() - 4:
            break
        size -= 1
    painter.setFont(font)
    painter.setPen(PLATE_TEXT)
    painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, label)
    painter.restore()


class PlateLabel(QWidget):
    """Plaka rozeti."""

    def __init__(self, plate: str = "", height: int = 30, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plate = plate
        self._alert = False
        self._height = height
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_plate(self, plate: str, *, alert: bool = False) -> None:
        self._plate, self._alert = plate, alert
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(int(self._height * 4.6), self._height)

    def paintEvent(self, _event) -> None:
        if not self._plate:
            return
        painter = QPainter(self)
        paint_plate(painter, QRectF(self.rect()), self._plate, alert=self._alert)
        painter.end()


class PlateDelegate(QStyledItemDelegate):
    """Tablolarda plaka sütununu plaka görünümünde çizer."""

    def paint(self, painter: QPainter, option, index) -> None:
        plate = index.data(Qt.ItemDataRole.DisplayRole)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight().color().darker(110))
        if not plate:
            return
        height = min(option.rect.height() - 8, 26)
        width = min(height * 4.4, option.rect.width() - 8)
        rect = QRectF(
            option.rect.left() + 6,
            option.rect.top() + (option.rect.height() - height) / 2,
            width,
            height,
        )
        alert = bool(index.data(Qt.ItemDataRole.UserRole + 1))
        paint_plate(painter, rect, str(plate), alert=alert)

    def sizeHint(self, option, index) -> QSize:
        return QSize(130, 36)
