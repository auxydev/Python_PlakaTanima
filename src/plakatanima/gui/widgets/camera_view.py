"""Canlı kamera görüntüsü ve tanıma katmanı."""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from plakatanima.camera.runner import CameraStatus
from plakatanima.camera.source import describe_source
from plakatanima.config import CameraConfig, CameraRole
from plakatanima.core.plate import format_plate
from plakatanima.db.models import EventAction
from plakatanima.gui import theme
from plakatanima.gui.utils import bgr_to_qimage, chip_color, icon
from plakatanima.gui.widgets.elided import ElidedLabel
from plakatanima.gui.widgets.plate import PlateLabel
from plakatanima.recognition.types import FrameAnalysis
from plakatanima.services.parking import ParkingResult

ANALYSIS_TTL = 1.5  # sn; daha eski tespit kutuları çizilmez
BANNER_TTL_MS = 7000

_STATUS_COLORS = {
    CameraStatus.RUNNING: "success",
    CameraStatus.LOADING: "info",
    CameraStatus.STARTING: "info",
    CameraStatus.RECONNECTING: "warning",
    CameraStatus.ERROR: "danger",
    CameraStatus.STOPPED: "muted",
}


class VideoWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._image: QImage | None = None
        self._frame_size = (0, 0)
        self._analysis: FrameAnalysis | None = None
        self._analysis_time = 0.0
        self.roi: tuple[float, float, float, float] | None = None
        self.placeholder = "Görüntü bekleniyor…"

    def set_frame(self, frame: np.ndarray) -> None:
        self._image = bgr_to_qimage(frame)
        self._frame_size = (frame.shape[1], frame.shape[0])
        self.update()

    def set_analysis(self, analysis: FrameAnalysis) -> None:
        self._analysis = analysis
        self._analysis_time = time.monotonic()

    def clear(self) -> None:
        self._image = None
        self._analysis = None
        self.update()

    def heightForWidth(self, width: int) -> int:
        return int(width * 9 / 16)

    def paintEvent(self, _event) -> None:
        palette = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor(palette.video_bg))

        if self._image is None:
            painter.setPen(QColor(palette.muted))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.placeholder)
            painter.end()
            return

        fw, fh = self._frame_size
        scale = min(self.width() / fw, self.height() / fh)
        tw, th = fw * scale, fh * scale
        ox, oy = (self.width() - tw) / 2, (self.height() - th) / 2
        painter.drawImage(QRectF(ox, oy, tw, th), self._image)

        def rect(box) -> QRectF:
            return QRectF(
                ox + box.x1 * scale, oy + box.y1 * scale, box.width * scale, box.height * scale
            )

        if self.roi is not None:
            x1, y1, x2, y2 = self.roi
            pen = QPen(QColor(255, 255, 255, 120), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(ox + x1 * tw, oy + y1 * th, (x2 - x1) * tw, (y2 - y1) * th))

        analysis = self._analysis
        if analysis is not None and time.monotonic() - self._analysis_time <= ANALYSIS_TTL:
            label_font = QFont()
            label_font.setPixelSize(max(int(12 * max(scale, 0.8)), 11))
            label_font.setBold(True)
            painter.setFont(label_font)
            for vehicle in analysis.vehicles:
                color = QColor(vehicle.vehicle_type.color)
                r = rect(vehicle.bbox)
                painter.setPen(QPen(color, 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(r, 4, 4)
                self._tag(
                    painter,
                    r.left(),
                    r.top(),
                    f"{vehicle.vehicle_type.label} %{vehicle.confidence * 100:.0f}",
                    color,
                )
            for raw in analysis.rejected:
                painter.setPen(QPen(QColor(160, 160, 160), 1, Qt.PenStyle.DashLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(rect(raw.bbox))
            plate_color = QColor(palette.success)
            for plate in analysis.plates:
                r = rect(plate.bbox)
                painter.setPen(QPen(plate_color, 2.5))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(r)
                self._tag(
                    painter,
                    r.left(),
                    r.bottom() + 22,
                    f"{format_plate(plate.text)}  %{plate.confidence * 100:.0f}",
                    plate_color,
                )
        painter.end()

    @staticmethod
    def _tag(painter: QPainter, x: float, y: float, text: str, color: QColor) -> None:
        metrics = painter.fontMetrics()
        w, h = metrics.horizontalAdvance(text) + 10, metrics.height() + 4
        box = QRectF(x, max(y - h, 0), w, h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(box, 3, 3)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)


class CameraView(QFrame):
    """Kamera kartı: başlık, durum, canlı görüntü ve son okunan plaka."""

    def __init__(self, index: int, camera: CameraConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.index = index
        self.camera = camera
        self.setObjectName("Card")
        self._frames = 0
        self._fps_started = time.monotonic()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 10, 14, 10)
        hl.setSpacing(8)
        cam_icon = QLabel()
        cam_icon.setPixmap(icon("mdi6.cctv", theme.current().muted).pixmap(18, 18))
        hl.addWidget(cam_icon)
        name = QLabel(camera.name)
        name.setObjectName("SectionTitle")
        name.setToolTip(describe_source(camera.source))
        hl.addWidget(name)
        self.role_chip = QLabel(camera.role.label)
        palette = theme.current()
        role_color = palette.success if camera.role is CameraRole.ENTRY else palette.info
        self.role_chip.setStyleSheet(
            f"background:{chip_color(role_color, 50)}; color:{role_color};"
            "border-radius:6px; padding:2px 8px; font-weight:600; font-size:8.5pt;"
        )
        hl.addWidget(self.role_chip)
        self.stats_label = ElidedLabel("")
        self.stats_label.setObjectName("Muted")
        self.stats_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        hl.addWidget(self.stats_label, 1)
        self.status_dot = QLabel("●")
        hl.addWidget(self.status_dot)
        self.status_label = QLabel("")
        hl.addWidget(self.status_label)
        layout.addWidget(header)

        self.video = VideoWidget()
        self.video.roi = camera.roi
        layout.addWidget(self.video, 1)

        self.banner = QWidget()
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(14, 8, 14, 10)
        bl.setSpacing(10)
        self.banner_plate = PlateLabel(height=28)
        bl.addWidget(self.banner_plate)
        self.banner_text = QLabel("")
        self.banner_text.setWordWrap(True)
        self.banner_text.setMinimumWidth(10)
        bl.addWidget(self.banner_text, 1)
        layout.addWidget(self.banner)
        self.banner.setVisible(False)
        self._banner_timer = QTimer(self, singleShot=True, interval=BANNER_TTL_MS)
        self._banner_timer.timeout.connect(lambda: self.banner.setVisible(False))

        self.set_status(CameraStatus.STARTING, "")

    def set_frame(self, frame: np.ndarray) -> None:
        self.video.set_frame(frame)
        self._frames += 1
        elapsed = time.monotonic() - self._fps_started
        if elapsed >= 2.0:
            self._display_fps = self._frames / elapsed
            self._frames = 0
            self._fps_started = time.monotonic()

    def set_analysis(self, analysis: FrameAnalysis) -> None:
        self.video.set_analysis(analysis)
        fps = getattr(self, "_display_fps", 0.0)
        self.stats_label.setText(f"{fps:.0f} fps · {analysis.elapsed_ms:.0f} ms")

    def set_status(self, status: CameraStatus, message: str) -> None:
        palette = theme.current()
        color = getattr(palette, _STATUS_COLORS[status])
        self.status_dot.setStyleSheet(f"color:{color}; font-size:11pt;")
        self.status_label.setText(status.label)
        self.status_label.setToolTip(message)
        if status is not CameraStatus.RUNNING:
            self.video.placeholder = f"{status.label}\n{message}" if message else status.label
            if status in (CameraStatus.RECONNECTING, CameraStatus.ERROR, CameraStatus.STOPPED):
                self.video.clear()
        self.video.update()

    def show_result(self, result: ParkingResult) -> None:
        palette = theme.current()
        alert = result.is_alert
        self.banner_plate.set_plate(result.plate, alert=result.is_blacklisted)
        details = result.message.split(" — ", 1)[-1]
        head = result.action.label
        color = {
            EventAction.ENTRY: palette.success,
            EventAction.EXIT: palette.info,
            EventAction.UNMATCHED_EXIT: palette.warning,
        }.get(result.action, palette.muted)
        if result.is_blacklisted:
            color = palette.danger
        self.banner_text.setText(f"<b style='color:{color}'>{head}</b> &nbsp; {details}")
        self.banner.setStyleSheet(
            f"background:{chip_color(color, 60 if alert else 30)};"
            "border-bottom-left-radius:12px; border-bottom-right-radius:12px;"
        )
        self.banner.setVisible(True)
        self._banner_timer.start()
