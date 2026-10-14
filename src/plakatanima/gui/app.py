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
from plakatanima.db.models import User
from plakatanima.gui import theme
from plakatanima.gui.auth_dialogs import ChangePasswordDialog, LoginDialog
from plakatanima.gui.controller import Controller
from plakatanima.gui.main_window import MainWindow
from plakatanima.gui.utils import icon
from plakatanima.paths import AppPaths
from plakatanima.services.maintenance import backup_if_due

log = logging.getLogger(__name__)


def create_application() -> QApplication:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setOrganizationName(APP_NAME)
    QLocale.setDefault(QLocale(QLocale.Language.Turkish, QLocale.Country.Turkey))
    return app


def prepare_theme(ctx: AppContext) -> QApplication:
    app = create_application()
    theme.apply_theme(app, ctx.config.ui.theme)
    app.setWindowIcon(icon("mdi6.car-search", theme.current().accent))
    return app


def build_window(
    ctx: AppContext, *, user: User | None = None, start_cameras: bool = True
) -> MainWindow:
    """Uygulama penceresini kurar (testlerde kameralar başlatılmadan da kullanılır)."""
    prepare_theme(ctx)
    controller = Controller(ctx)
    controller.current_user = user
    window = MainWindow(controller)
    if start_cameras:
        controller.start_cameras()
    return window


def login(ctx: AppContext) -> User | None:
    """Giriş ekranı; ilk girişte parola değişikliği zorunludur. Vazgeçilirse ``None``."""
    dialog = LoginDialog(ctx.users, ctx.config.parking.lot_name)
    if not dialog.exec() or dialog.user is None:
        return None
    user = dialog.user
    if user.must_change_password:
        if not ChangePasswordDialog(ctx.users, user, forced=True).exec():
            return None
        user = ctx.users.get(user.username)
    return user


def _background_maintenance(ctx: AppContext) -> None:
    cleanup_snapshots(ctx.paths.captures_dir, ctx.config.parking.snapshot_retention_days)
    if not ctx.demo:
        backup_if_due(ctx.db, ctx.paths.backups_dir)


def run_gui(config_path: Path | None, paths: AppPaths, *, demo: bool = False) -> int:
    app = create_application()
    # Giriş diyaloğu kapanınca uygulama "son pencere kapandı" diye sonlanmasın;
    # olay döngüsünü yalnızca ana pencere bitirir (bkz. MainWindow.closeEvent).
    app.setQuitOnLastWindowClosed(False)
    ctx = AppContext.create(config_path, paths, demo=demo)
    threading.Thread(
        target=_background_maintenance, args=(ctx,), daemon=True, name="maintenance"
    ).start()
    prepare_theme(ctx)
    try:
        while True:
            user = None
            if ctx.config.ui.require_login:
                user = login(ctx)
                if user is None:
                    return 0
            window = build_window(ctx, user=user)
            window.quit_app_on_close = True
            window.show()
            code = app.exec()
            window.controller.shutdown()
            if not window.logout_requested:
                return code
            window.deleteLater()  # çıkış yapıldı: giriş ekranına dön
    finally:
        ctx.close()
