"""Giriş, parola değiştirme ve kullanıcı düzenleme diyalogları."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from plakatanima import APP_DISPLAY_NAME
from plakatanima.db.models import User, UserRole
from plakatanima.gui import theme
from plakatanima.gui.utils import enum_data, icon, muted
from plakatanima.services.auth import (
    DEFAULT_ADMIN,
    DEFAULT_PASSWORD,
    AuthError,
    UserService,
)


def _password_field(placeholder: str = "") -> QLineEdit:
    field = QLineEdit()
    field.setEchoMode(QLineEdit.EchoMode.Password)
    field.setPlaceholderText(placeholder)
    return field


def _buttons(dialog: QDialog, ok_text: str) -> QDialogButtonBox:
    box = QDialogButtonBox()
    ok = box.addButton(ok_text, QDialogButtonBox.ButtonRole.AcceptRole)
    ok.setProperty("variant", "primary")
    ok.setDefault(True)
    box.addButton("Vazgeç", QDialogButtonBox.ButtonRole.RejectRole)
    box.rejected.connect(dialog.reject)
    return box


def _error_label() -> QLabel:
    label = QLabel("")
    label.setStyleSheet(f"color:{theme.current().danger};")
    label.setWordWrap(True)
    return label


class LoginDialog(QDialog):
    def __init__(self, users: UserService, lot_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.users = users
        self.user: User | None = None
        self.setWindowTitle(f"{APP_DISPLAY_NAME} — Giriş")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(12)

        logo = QLabel()
        logo.setPixmap(icon("mdi6.car-search", theme.current().accent).pixmap(48, 48))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo)
        title = QLabel(lot_name)
        title.setObjectName("PageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        subtitle = muted("Devam etmek için giriş yapın")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        form = QFormLayout()
        self.username = QLineEdit()
        self.username.setPlaceholderText("kullanıcı adı")
        form.addRow("Kullanıcı", self.username)
        self.password = _password_field("parola")
        form.addRow("Parola", self.password)
        layout.addLayout(form)
        self.error = _error_label()
        layout.addWidget(self.error)

        default_admin = users.get(DEFAULT_ADMIN)
        if default_admin is not None and default_admin.must_change_password:
            hint = muted(f"İlk giriş: {DEFAULT_ADMIN} / {DEFAULT_PASSWORD} (parola değiştirilecek)")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(hint)
            self.username.setText(DEFAULT_ADMIN)
            self.password.setFocus()

        buttons = _buttons(self, "Giriş")
        buttons.accepted.connect(self._login)
        layout.addWidget(buttons)

    def _login(self) -> None:
        user = self.users.authenticate(self.username.text(), self.password.text())
        if user is None:
            self.error.setText("Kullanıcı adı veya parola hatalı.")
            self.password.selectAll()
            self.password.setFocus()
            return
        self.user = user
        self.accept()


class ChangePasswordDialog(QDialog):
    """Kullanıcının kendi parolasını değiştirmesi (ilk girişte zorunlu)."""

    def __init__(
        self, users: UserService, user: User, *, forced: bool = False, parent=None
    ) -> None:
        super().__init__(parent)
        self.users = users
        self.user = user
        self.setWindowTitle("Parola Değiştir")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        if forced:
            layout.addWidget(muted("Güvenliğiniz için ilk girişte parolanızı değiştirmelisiniz."))
        form = QFormLayout()
        self.old = _password_field()
        self.new = _password_field()
        self.repeat = _password_field()
        form.addRow("Mevcut parola", self.old)
        form.addRow("Yeni parola", self.new)
        form.addRow("Yeni parola (tekrar)", self.repeat)
        layout.addLayout(form)
        self.error = _error_label()
        layout.addWidget(self.error)
        buttons = _buttons(self, "Kaydet")
        buttons.accepted.connect(self._save)
        layout.addWidget(buttons)

    def _save(self) -> None:
        if self.new.text() != self.repeat.text():
            self.error.setText("Yeni parolalar eşleşmiyor.")
            return
        try:
            self.users.change_password(self.user.id, self.old.text(), self.new.text())
        except AuthError as exc:
            self.error.setText(str(exc))
            return
        self.accept()


class UserDialog(QDialog):
    """Yönetici için kullanıcı ekleme/düzenleme."""

    def __init__(self, users: UserService, user: User | None = None, parent=None) -> None:
        super().__init__(parent)
        self.users = users
        self.user = user
        self.setWindowTitle("Kullanıcıyı Düzenle" if user else "Yeni Kullanıcı")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.username = QLineEdit(user.username if user else "")
        self.username.setEnabled(user is None)
        form.addRow("Kullanıcı adı", self.username)
        self.full_name = QLineEdit(user.full_name if user else "")
        form.addRow("Ad soyad", self.full_name)
        self.role = QComboBox()
        for role in UserRole:
            self.role.addItem(role.label, role)
        self.role.setCurrentIndex(self.role.findData(user.role if user else UserRole.OPERATOR))
        form.addRow("Rol", self.role)
        self.active = QCheckBox("Etkin")
        self.active.setChecked(user.is_active if user else True)
        form.addRow("", self.active)
        self.password = _password_field("en az 4 karakter")
        self.repeat = _password_field()
        self.must_change = QCheckBox("İlk girişte parolasını değiştirsin")
        self.must_change.setChecked(True)
        if user is None:
            form.addRow("Parola", self.password)
            form.addRow("Parola (tekrar)", self.repeat)
            form.addRow("", self.must_change)
        layout.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(
            muted(
                "Operatör: giriş/çıkış ve ödeme işlemleri. Yönetici: ayarlar, tarifeler, "
                "kullanıcılar ve kayıt silme."
            )
        )
        layout.addLayout(row)
        self.error = _error_label()
        layout.addWidget(self.error)
        buttons = _buttons(self, "Kaydet")
        buttons.accepted.connect(self._save)
        layout.addWidget(buttons)

    def _save(self) -> None:
        role = enum_data(self.role, UserRole)
        try:
            if self.user is None:
                if self.password.text() != self.repeat.text():
                    self.error.setText("Parolalar eşleşmiyor.")
                    return
                created = self.users.create(
                    self.username.text(),
                    self.password.text(),
                    role=role,
                    full_name=self.full_name.text(),
                    must_change_password=self.must_change.isChecked(),
                )
                if not self.active.isChecked():
                    self.users.update(created.id, is_active=False)
            else:
                self.users.update(
                    self.user.id,
                    full_name=self.full_name.text(),
                    role=role,
                    is_active=self.active.isChecked(),
                )
        except AuthError as exc:
            self.error.setText(str(exc))
            return
        self.accept()


class ResetPasswordDialog(QDialog):
    def __init__(self, users: UserService, user: User, parent=None) -> None:
        super().__init__(parent)
        self.users = users
        self.user = user
        self.setWindowTitle(f"Parola Sıfırla — {user.username}")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.password = _password_field("en az 4 karakter")
        self.repeat = _password_field()
        form.addRow("Yeni parola", self.password)
        form.addRow("Tekrar", self.repeat)
        self.must_change = QCheckBox("İlk girişte değiştirsin")
        self.must_change.setChecked(True)
        form.addRow("", self.must_change)
        layout.addLayout(form)
        self.error = _error_label()
        layout.addWidget(self.error)
        buttons = _buttons(self, "Sıfırla")
        buttons.accepted.connect(self._save)
        layout.addWidget(buttons)

    def _save(self) -> None:
        if self.password.text() != self.repeat.text():
            self.error.setText("Parolalar eşleşmiyor.")
            return
        try:
            self.users.set_password(
                self.user.id, self.password.text(), must_change=self.must_change.isChecked()
            )
        except AuthError as exc:
            self.error.setText(str(exc))
            return
        self.accept()
