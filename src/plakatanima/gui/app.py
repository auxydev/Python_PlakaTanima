"""Masaüstü uygulamasını başlatır."""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QApplication

from plakatanima import APP_DISPLAY_NAME, APP_NAME
from plakatanima.camera.snapshot import cleanup_snapshots
from plakatanima.context import AppContext
from plakatanima.gui import theme
from plakatanima.gui.controller import Controller
from plakatanima.gui.main_window import MainWindow
from plakatanima.gui.utils import icon
from plakatanima.paths import AppPaths

log = logging.getLogger(__name__)


def create_application() -> QApplication:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setOrganizationName(APP_NAME)
    QLocale.setDefault(QLocale(QLocale.Language.Turkish, QLocale.Country.Turkey))
    return app


def build_window(ctx: AppContext, *, start_cameras: bool = True) -> MainWindow:
    """Uygulama penceresini kurar (testlerde kameralar başlatılmadan da kullanılır)."""
    app = create_application()
    theme.apply_theme(app, ctx.config.ui.theme)
    app.setWindowIcon(icon("mdi6.car-search", theme.current().accent))
    controller = Controller(ctx)
    window = MainWindow(controller)
    if start_cameras:
        controller.start_cameras()
    return window


def run_gui(config_path: Path | None, paths: AppPaths, *, demo: bool = False) -> int:
    app = create_application()
    ctx = AppContext.create(config_path, paths, demo=demo)
    threading.Thread(
        target=cleanup_snapshots,
        args=(ctx.paths.captures_dir, ctx.config.parking.snapshot_retention_days),
        daemon=True,
        name="snapshot-cleanup",
    ).start()
    window = build_window(ctx)
    window.show()
    try:
        return app.exec()
    finally:
        window.controller.shutdown()
        ctx.close()
