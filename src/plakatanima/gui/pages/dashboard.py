"""Gösterge paneli: canlı kameralar, doluluk, günlük özet ve son geçişler."""

from __future__ import annotations

import math
from datetime import datetime

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from plakatanima.config import CameraRole
from plakatanima.core.formatting import format_money
from plakatanima.gui import theme
from plakatanima.gui.controller import Controller
from plakatanima.gui.utils import Card, button, muted, page_header, section_title
from plakatanima.gui.widgets.camera_view import CameraView
from plakatanima.gui.widgets.cards import OccupancyCard, StatCard
from plakatanima.gui.widgets.event_feed import EventFeed, FeedEntry
from plakatanima.services.parking import ParkingResult

_WEEKDAYS = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")
_MONTHS = (
    "Ocak",
    "Şubat",
    "Mart",
    "Nisan",
    "Mayıs",
    "Haziran",
    "Temmuz",
    "Ağustos",
    "Eylül",
    "Ekim",
    "Kasım",
    "Aralık",
)


class DashboardPage(QWidget):
    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageRoot")
        self.controller = controller
        self.ctx = controller.ctx
        palette = theme.current()

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        entry_btn = button("Manuel Giriş", "mdi6.login", variant="primary")
        entry_btn.clicked.connect(lambda: controller.manual_pass(CameraRole.ENTRY))
        exit_btn = button("Manuel Çıkış", "mdi6.logout")
        exit_btn.clicked.connect(lambda: controller.manual_pass(CameraRole.EXIT))
        self.clock = muted("")
        self.header = page_header(
            self.ctx.config.parking.lot_name, "", [self.clock, entry_btn, exit_btn]
        )
        root.addWidget(self.header)

        cards = QHBoxLayout()
        cards.setSpacing(14)
        self.occupancy = OccupancyCard()
        self.entries = StatCard("Bugün giriş", "mdi6.arrow-down-bold-circle", palette.success)
        self.exits = StatCard("Bugün çıkış", "mdi6.arrow-up-bold-circle", palette.info)
        self.revenue = StatCard("Bugün tahsilat", "mdi6.cash-multiple", palette.warning)
        cards.addWidget(self.occupancy, 3)
        cards.addWidget(self.entries, 2)
        cards.addWidget(self.exits, 2)
        cards.addWidget(self.revenue, 2)
        root.addLayout(cards)

        body = QHBoxLayout()
        body.setSpacing(16)
        self.camera_area = QWidget()
        self.camera_grid = QGridLayout(self.camera_area)
        self.camera_grid.setContentsMargins(0, 0, 0, 0)
        self.camera_grid.setSpacing(14)
        self._columns = 0
        self.camera_area.installEventFilter(self)
        body.addWidget(self.camera_area, 7)

        feed_card = Card(padding=12)
        head = QHBoxLayout()
        head.addWidget(section_title("Son Geçişler"))
        head.addStretch(1)
        head.addWidget(muted("çift tıkla: ayrıntı"))
        feed_card.body.addLayout(head)
        self.feed = EventFeed(limit=self.ctx.config.ui.recent_events_limit)
        self.feed.session_activated.connect(controller.show_session)
        feed_card.body.addWidget(self.feed, 1)
        feed_card.setMinimumWidth(380)
        body.addWidget(feed_card, 3)
        root.addLayout(body, 1)

        self.views: dict[int, CameraView] = {}
        bridge = controller.bridge
        bridge.frame_ready.connect(self._on_frame)
        bridge.analysis_ready.connect(self._on_analysis)
        bridge.status_changed.connect(self._on_status)
        controller.result_added.connect(self._on_result)
        controller.data_changed.connect(self.refresh_stats)
        controller.cameras_restarted.connect(self.build_cameras)

        self._timer = QTimer(self, interval=30_000)
        self._timer.timeout.connect(self.refresh_stats)
        self._timer.start()
        self._clock_timer = QTimer(self, interval=1000)
        self._clock_timer.timeout.connect(self._tick)
        self._clock_timer.start()
        self._tick()

        self.build_cameras()
        self.load_events()
        self.refresh_stats()

    # ------------------------------------------------------------- kameralar
    def build_cameras(self) -> None:
        while self.camera_grid.count():
            item = self.camera_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.views.clear()
        cameras = [(i, c) for i, c in enumerate(self.ctx.config.cameras) if c.enabled]
        if not cameras:
            empty = Card()
            label = QLabel("Etkin kamera yok.\nAyarlar › Kameralar bölümünden kamera ekleyin.")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setObjectName("Muted")
            empty.body.addWidget(label)
            self.camera_grid.addWidget(empty, 0, 0)
            return
        for index, camera in cameras:
            view = CameraView(index, camera)
            runner = self.controller.cameras.runner(index)
            if runner is not None:
                view.set_status(runner.status, runner.status_message)
            self.views[index] = view
        self._columns = 0
        self._arrange_cameras()

    _CHROME = 92  # kamera kartının başlık + plaka şeridi yüksekliği (px)

    def _cell_size(self, count: int, columns: int) -> tuple[float, float]:
        spacing = self.camera_grid.spacing()
        rows = math.ceil(count / columns)
        cell_w = (max(self.camera_area.width(), 1) - spacing * (columns - 1)) / columns
        cell_h = (max(self.camera_area.height(), 1) - spacing * (rows - 1)) / rows
        return cell_w, cell_h

    def _best_columns(self, count: int) -> int:
        """Görüntüleri (16:9) en büyük gösterecek sütun sayısı."""

        def scale(columns: int) -> float:
            cell_w, cell_h = self._cell_size(count, columns)
            return min(cell_w / 16, (cell_h - self._CHROME) / 9)

        return max(range(1, count + 1), key=scale)

    def _arrange_cameras(self) -> None:
        views = list(self.views.values())
        if not views:
            return
        columns = self._best_columns(len(views))
        # Kart yüksekliği görüntü oranına göre: kart içinde boş siyah alan kalmasın.
        cell_w, cell_h = self._cell_size(len(views), columns)
        height = int(min(cell_h, cell_w * 9 / 16 + self._CHROME))
        for view in views:
            view.setFixedHeight(max(height, 200))
        if columns == self._columns:
            return
        self._columns = columns
        for view in views:
            self.camera_grid.removeWidget(view)
        for r in range(self.camera_grid.rowCount()):
            self.camera_grid.setRowStretch(r, 0)
        for c in range(self.camera_grid.columnCount()):
            self.camera_grid.setColumnStretch(c, 0)
        for n, view in enumerate(views):
            self.camera_grid.addWidget(view, n // columns, n % columns)
        rows = math.ceil(len(views) / columns)
        self.camera_grid.setRowStretch(rows, 1)  # kalan boşluk en altta
        for c in range(columns):
            self.camera_grid.setColumnStretch(c, 1)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.camera_area and event.type() == QEvent.Type.Resize:
            self._arrange_cameras()
        return False

    def _on_frame(self, index: int, image) -> None:
        view = self.views.get(index)
        if view is not None and self.isVisible():
            view.set_frame(image)

    def _on_analysis(self, index: int, analysis) -> None:
        view = self.views.get(index)
        if view is not None:
            view.set_analysis(analysis)

    def _on_status(self, index: int, status, message: str) -> None:
        view = self.views.get(index)
        if view is not None:
            view.set_status(status, message)

    # ---------------------------------------------------------------- veriler
    def _on_result(self, result: ParkingResult) -> None:
        self.feed.add_entry(FeedEntry.from_result(result))
        for view in self.views.values():
            if view.camera.name == result.camera_name:
                view.show_result(result)
        self.refresh_stats()

    def load_events(self) -> None:
        events = self.ctx.parking.recent_events(self.ctx.config.ui.recent_events_limit)
        self.feed.set_entries([FeedEntry.from_event(e) for e in events])

    def refresh_stats(self) -> None:
        stats = self.ctx.parking.dashboard_stats()
        currency = self.ctx.config.parking.currency
        self.occupancy.set_values(stats.inside, stats.capacity, stats.inside_by_type)
        self.entries.set_value(str(stats.entries_today), "kayıtlı giriş")
        self.exits.set_value(str(stats.exits_today), "tamamlanan çıkış")
        hint = (
            f"{stats.unpaid_count} ödeme bekliyor" if stats.unpaid_count else "bekleyen ödeme yok"
        )
        self.revenue.set_value(format_money(stats.revenue_today, currency), hint)

    def _tick(self) -> None:
        now = datetime.now()
        self.clock.setText(
            f"{now.day} {_MONTHS[now.month - 1]} {now.year}, {_WEEKDAYS[now.weekday()]}"
            f"  ·  {now:%H:%M:%S}"
        )
