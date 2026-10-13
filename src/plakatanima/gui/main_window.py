"""Ana pencere: kenar menü + sayfalar + durum çubuğu."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from plakatanima import APP_DISPLAY_NAME, __version__
from plakatanima.camera.runner import CameraStatus
from plakatanima.config import CameraRole
from plakatanima.gui import theme
from plakatanima.gui.controller import Controller
from plakatanima.gui.pages.dashboard import DashboardPage
from plakatanima.gui.pages.inside import InsidePage
from plakatanima.gui.pages.sessions import SessionsPage
from plakatanima.gui.pages.settings import SettingsPage
from plakatanima.gui.pages.tariffs import TariffsPage
from plakatanima.gui.pages.vehicles import VehiclesPage
from plakatanima.gui.utils import chip_color, icon

PageFactory = Callable[[Controller], QWidget]


class MainWindow(QMainWindow):
    def __init__(self, controller: Controller) -> None:
        super().__init__()
        self.controller = controller
        self.ctx = controller.ctx
        title = APP_DISPLAY_NAME + (" — DEMO" if self.ctx.demo else "")
        self.setWindowTitle(title)
        self.setWindowIcon(icon("mdi6.car-search", theme.current().accent))
        self.resize(1480, 920)
        self.setMinimumSize(1100, 700)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(central)

        self.sidebar = self._build_sidebar()
        layout.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self.pages: dict[str, QWidget] = {}
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for key, label, icon_name, factory in self.page_definitions():
            self.add_page(key, label, icon_name, factory)
        self._nav_layout.addStretch(1)
        self._nav_layout.addWidget(self._footer())
        self.show_page("dashboard")

        self._build_status_bar()
        controller.attach(self)
        controller.bridge.status_changed.connect(lambda *_: self._update_camera_status())
        controller.cameras_restarted.connect(self._update_camera_status)

        QShortcut(QKeySequence("F2"), self, lambda: controller.manual_pass(CameraRole.ENTRY))
        QShortcut(QKeySequence("F3"), self, lambda: controller.manual_pass(CameraRole.EXIT))
        for i, key in enumerate(self.pages, start=1):
            QShortcut(QKeySequence(f"Ctrl+{i}"), self, lambda k=key: self.show_page(k))

    def page_definitions(self) -> list[tuple[str, str, str, PageFactory]]:
        return [
            ("dashboard", "Gösterge Paneli", "mdi6.view-dashboard-outline", DashboardPage),
            ("inside", "İçerideki Araçlar", "mdi6.parking", InsidePage),
            ("sessions", "Geçiş Kayıtları", "mdi6.history", SessionsPage),
            ("vehicles", "Araçlar", "mdi6.card-account-details-outline", VehiclesPage),
            ("tariffs", "Tarifeler", "mdi6.cash-multiple", TariffsPage),
            ("settings", "Ayarlar", "mdi6.cog-outline", SettingsPage),
        ]

    # --------------------------------------------------------------- kenar menü
    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(236)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(4)

        brand = QHBoxLayout()
        logo = QLabel()
        logo.setFixedSize(40, 40)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setPixmap(icon("mdi6.car-search", "#FFFFFF").pixmap(24, 24))
        logo.setStyleSheet(f"background:{theme.current().accent}; border-radius:10px;")
        brand.addWidget(logo)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        title = QLabel("Plaka Tanıma")
        title.setObjectName("SidebarTitle")
        texts.addWidget(title)
        subtitle = QLabel(self.ctx.config.parking.lot_name)
        subtitle.setObjectName("SidebarSubtitle")
        texts.addWidget(subtitle)
        brand.addLayout(texts, 1)
        layout.addLayout(brand)
        if self.ctx.demo:
            demo = QLabel("DEMO MODU")
            warning = theme.current().warning
            demo.setStyleSheet(
                f"background:{chip_color(warning, 60)}; color:{warning}; border-radius:6px;"
                "padding:3px 8px; font-weight:700; font-size:8.5pt;"
            )
            demo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addSpacing(8)
            layout.addWidget(demo)
        layout.addSpacing(18)
        self._nav_layout = layout
        return sidebar

    def _footer(self) -> QWidget:
        footer = QLabel(f"v{__version__}  ·  F2 giriş  ·  F3 çıkış")
        footer.setObjectName("SidebarFooter")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.user_label = footer
        return footer

    def add_page(self, key: str, label: str, icon_name: str, factory: PageFactory) -> None:
        page = factory(self.controller)
        self.pages[key] = page
        self.stack.addWidget(page)
        btn = QPushButton(f"  {label}")
        btn.setObjectName("NavButton")
        btn.setIcon(icon(icon_name, theme.current().sidebar_text))
        btn.setIconSize(QSize(20, 20))
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setProperty("page_key", key)
        btn.clicked.connect(lambda: self.show_page(key))
        self.nav_group.addButton(btn)
        self._nav_layout.addWidget(btn)

    def show_page(self, key: str) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        for btn in self.nav_group.buttons():
            btn.setChecked(btn.property("page_key") == key)

    # ------------------------------------------------------------ durum çubuğu
    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        self.camera_status = QLabel("")
        bar.addWidget(self.camera_status)
        database = QLabel(self.ctx.db.engine.url.render_as_string(hide_password=True))
        database.setObjectName("Muted")
        bar.addPermanentWidget(database)
        self._update_camera_status()

    def _update_camera_status(self) -> None:
        runners = self.controller.cameras.runners
        if not runners:
            self.camera_status.setText("Kamera çalışmıyor")
            return
        palette = theme.current()
        parts = []
        for runner in runners:
            color = {
                CameraStatus.RUNNING: palette.success,
                CameraStatus.ERROR: palette.danger,
                CameraStatus.RECONNECTING: palette.warning,
            }.get(runner.status, palette.muted)
            parts.append(
                f"<span style='color:{color}'>●</span> {runner.camera.name}: {runner.status.label}"
            )
        self.camera_status.setText("&nbsp;&nbsp;&nbsp;".join(parts))

    def closeEvent(self, event) -> None:
        self.controller.shutdown()
        super().closeEvent(event)
