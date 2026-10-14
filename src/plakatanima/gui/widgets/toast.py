"""Pencerenin sağ üst köşesinde beliren bildirimler."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from plakatanima.gui import theme
from plakatanima.gui.utils import icon

_ICONS = {
    "success": "mdi6.check-circle",
    "info": "mdi6.information",
    "warning": "mdi6.alert",
    "danger": "mdi6.alert-octagon",
}


class Toast(QFrame):
    def __init__(
        self,
        parent: QWidget,
        title: str,
        text: str,
        level: str,
        *,
        action: tuple[str, Callable[[], None]] | None = None,
        timeout_ms: int = 6000,
    ) -> None:
        super().__init__(parent)
        palette = theme.current()
        color = getattr(palette, level)
        self.setObjectName("Toast")
        self.setStyleSheet(
            f"#Toast {{ background:{palette.surface}; border:1px solid {palette.border};"
            f" border-left:4px solid {color}; border-radius:10px; }}"
        )
        self.setFixedWidth(360)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 10, 10)
        layout.setSpacing(10)
        ico = QLabel()
        ico.setPixmap(icon(_ICONS.get(level, "mdi6.information"), color).pixmap(22, 22))
        ico.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(ico)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        head = QLabel(title)
        head.setStyleSheet("font-weight:700;")
        texts.addWidget(head)
        body = QLabel(text)
        body.setWordWrap(True)
        body.setObjectName("Muted")
        texts.addWidget(body)
        if action is not None:
            label, callback = action
            btn = QPushButton(label)
            btn.setProperty("variant", "primary")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(callback)
            btn.clicked.connect(self.close)
            row = QHBoxLayout()
            row.addStretch(1)
            row.addWidget(btn)
            texts.addLayout(row)
        layout.addLayout(texts, 1)
        close = QPushButton("✕")
        close.setFlat(True)
        close.setFixedSize(24, 24)
        close.setStyleSheet("border:none; background:transparent;")
        close.clicked.connect(self.close)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        QTimer.singleShot(timeout_ms, self.close)


class ToastManager(QObject):
    """Bildirimleri üst üste dizer ve pencere boyutu değişince yeniden konumlar."""

    def __init__(self, host: QWidget, max_visible: int = 4) -> None:
        super().__init__(host)
        self._host = host
        self._max = max_visible
        self._toasts: list[Toast] = []
        host.installEventFilter(self)

    def show(self, title: str, text: str, level: str = "info", **kwargs) -> Toast:
        toast = Toast(self._host, title, text, level, **kwargs)
        toast.destroyed.connect(lambda *_: self._forget(toast))
        self._toasts.insert(0, toast)
        while len(self._toasts) > self._max:
            self._toasts.pop().close()
        toast.show()
        toast.raise_()
        self._layout()
        return toast

    def _forget(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._layout()

    def _layout(self) -> None:
        y = 16
        for toast in list(self._toasts):
            try:
                toast.adjustSize()
                toast.move(self._host.width() - toast.width() - 20, y)
                y += toast.height() + 10
            except RuntimeError:  # silinmiş C++ nesnesi
                self._toasts.remove(toast)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._host and event.type() == QEvent.Type.Resize:
            self._layout()
        return False
