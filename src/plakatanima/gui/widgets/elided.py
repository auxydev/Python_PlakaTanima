"""Sığmayan metni "…" ile kısaltan etiket."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget


class ElidedLabel(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(20)

    def setText(self, text: str) -> None:
        super().setText(text)
        self.setToolTip(text)

    def minimumSizeHint(self) -> QSize:
        return QSize(20, super().minimumSizeHint().height())

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        metrics = self.fontMetrics()
        text = metrics.elidedText(self.text(), Qt.TextElideMode.ElideRight, self.width())
        painter.drawText(self.rect(), int(self.alignment()) | Qt.AlignmentFlag.AlignVCenter, text)
        painter.end()
