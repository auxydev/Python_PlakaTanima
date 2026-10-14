"""Kullanıcı yönetimi (yalnızca yönetici)."""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from plakatanima.core.formatting import format_datetime
from plakatanima.db.models import User, UserRole
from plakatanima.gui import theme
from plakatanima.gui.auth_dialogs import ResetPasswordDialog, UserDialog
from plakatanima.gui.controller import Controller
from plakatanima.gui.utils import button, confirm, icon, page_header, show_error
from plakatanima.gui.widgets.table import Column, DataTable, RowModel
from plakatanima.services.auth import AuthError


class UsersPage(QWidget):
    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageRoot")
        self.controller = controller
        self.users = controller.ctx.users
        palette = theme.current()

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)
        add = button("Yeni Kullanıcı", "mdi6.account-plus-outline", variant="primary")
        add.clicked.connect(self._add)
        edit = button("Düzenle", "mdi6.pencil-outline")
        edit.clicked.connect(self._edit_selected)
        reset = button("Parola Sıfırla", "mdi6.lock-reset")
        reset.clicked.connect(self._reset_selected)
        delete = button("Sil", "mdi6.delete-outline", variant="danger")
        delete.clicked.connect(self._delete_selected)
        root.addWidget(
            page_header(
                "Kullanıcılar",
                "Uygulamaya giriş yapabilecek yönetici ve operatörler",
                [add, edit, reset, delete],
            )
        )

        columns = [
            Column(
                "Kullanıcı adı",
                lambda u: u.username,
                icon=lambda u: icon(
                    "mdi6.shield-account" if u.role is UserRole.ADMIN else "mdi6.account",
                    palette.accent if u.role is UserRole.ADMIN else palette.muted,
                ),
                width=180,
            ),
            Column("Ad soyad", lambda u: u.full_name, width=200),
            Column("Rol", lambda u: u.role.label, width=120),
            Column(
                "Durum",
                lambda u: "Etkin" if u.is_active else "Pasif",
                color=lambda u: palette.success if u.is_active else palette.muted,
                width=100,
            ),
            Column(
                "Son giriş",
                lambda u: format_datetime(u.last_login),
                sort=lambda u: u.last_login,
                width=150,
            ),
            Column(
                "Not",
                lambda u: "İlk girişte parola değiştirecek" if u.must_change_password else "",
            ),
        ]
        self.model = RowModel(columns)
        self.table = DataTable(self.model, plate_column=None)
        self.table.doubleClicked.connect(lambda index: self._edit(self.table.row_for_index(index)))
        root.addWidget(self.table, 1)
        self.reload()

    def reload(self) -> None:
        self.model.set_rows(self.users.list())

    def _add(self) -> None:
        if UserDialog(self.users, parent=self).exec():
            self.reload()

    def _edit(self, user: User) -> None:
        if UserDialog(self.users, user, parent=self).exec():
            self.reload()

    def _edit_selected(self) -> None:
        user = self.table.selected_row()
        if user is not None:
            self._edit(user)

    def _reset_selected(self) -> None:
        user = self.table.selected_row()
        if user is not None and ResetPasswordDialog(self.users, user, parent=self).exec():
            self.controller.toast("Parola sıfırlandı", user.username, "success")
            self.reload()

    def _delete_selected(self) -> None:
        user = self.table.selected_row()
        if user is None:
            return
        current = self.controller.current_user
        if current is not None and current.id == user.id:
            show_error(self, "Oturum açık olan kullanıcı silinemez.")
            return
        if not confirm(self, "Kullanıcıyı sil", f"{user.username} silinsin mi?"):
            return
        try:
            self.users.delete(user.id)
        except AuthError as exc:
            show_error(self, str(exc))
            return
        self.reload()
