"""Arayüz yardımcıları."""

from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QImage
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from plakatanima.gui import theme

log = logging.getLogger(__name__)


def bgr_to_qimage(image: np.ndarray) -> QImage:
    """BGR numpy dizisini QImage'e çevirir (veri kopyalanır)."""
    if not image.flags["C_CONTIGUOUS"]:
        image = np.ascontiguousarray(image)
    height, width = image.shape[:2]
    if image.ndim == 2:
        qimage = QImage(
            image.data, width, height, image.strides[0], QImage.Format.Format_Grayscale8
        )
    else:
        qimage = QImage(image.data, width, height, image.strides[0], QImage.Format.Format_BGR888)
    return qimage.copy()


def icon(name: str, color: str | None = None) -> QIcon:
    try:
        import qtawesome as qta

        return qta.icon(name, color=color or theme.current().text)
    except Exception:  # simge yazı tipi yüklenemezse arayüz yine çalışsın
        log.debug("Simge yüklenemedi: %s", name, exc_info=True)
        return QIcon()


def enum_data(combo, enum_cls):
    """Açılır listedeki seçili değeri enum olarak döndürür.

    PySide6, ``StrEnum`` üyelerini öğe verisi olarak saklarken düz ``str``'e çevirir;
    bu yüzden okurken enum'a geri dönüştürülmelidir. Seçili veri yoksa ``None``.
    """
    value = combo.currentData()
    return None if value is None else enum_cls(value)


def set_variant(widget: QWidget, variant: str | None, prop: str = "variant") -> None:
    widget.setProperty(prop, variant)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def button(
    text: str,
    icon_name: str | None = None,
    *,
    variant: str | None = None,
    tooltip: str = "",
) -> QPushButton:
    btn = QPushButton(text)
    if icon_name:
        color = "#FFFFFF" if variant in ("primary", "success") else None
        if variant == "danger":
            color = theme.current().danger
        btn.setIcon(icon(icon_name, color))
    if variant:
        btn.setProperty("variant", variant)
    if tooltip:
        btn.setToolTip(tooltip)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


class Card(QFrame):
    """Kenarlıklı, yuvarlatılmış yüzey."""

    def __init__(self, parent: QWidget | None = None, *, padding: int = 16) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(10)


def page_header(title: str, subtitle: str = "", actions: list[QWidget] | None = None) -> QWidget:
    header = QWidget()
    layout = QHBoxLayout(header)
    layout.setContentsMargins(0, 0, 0, 0)
    texts = QVBoxLayout()
    texts.setSpacing(2)
    title_label = QLabel(title)
    title_label.setObjectName("PageTitle")
    texts.addWidget(title_label)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("PageSubtitle")
        texts.addWidget(sub)
    layout.addLayout(texts)
    layout.addStretch(1)
    for widget in actions or []:
        layout.addWidget(widget)
    return header


def muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    return label


def section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("SectionTitle")
    return label


def chip_color(color: str, alpha: int = 40) -> str:
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha / 255:.2f})"


def confirm(parent: QWidget, title: str, text: str) -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(title)
    box.setText(text)
    yes = box.addButton("Evet", QMessageBox.ButtonRole.YesRole)
    box.addButton("Vazgeç", QMessageBox.ButtonRole.NoRole)
    box.exec()
    return box.clickedButton() is yes


def show_error(parent: QWidget, text: str, title: str = "Hata") -> None:
    QMessageBox.critical(parent, title, text)


def show_info(parent: QWidget, text: str, title: str = "Bilgi") -> None:
    QMessageBox.information(parent, title, text)
