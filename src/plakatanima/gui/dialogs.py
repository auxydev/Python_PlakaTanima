"""Diyaloglar: manuel giriş/çıkış, ödeme, araç kaydı, geçiş detayı."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from plakatanima.config import CameraRole
from plakatanima.core.formatting import format_datetime, format_duration, format_money
from plakatanima.core.plate import clean_text, format_plate, normalize_plate, parse_plate
from plakatanima.core.vehicle import VehicleType
from plakatanima.db.models import ParkingSession, PaymentMethod, SessionStatus, Vehicle
from plakatanima.gui import theme
from plakatanima.gui.utils import button, enum_data, icon, muted, section_title, show_error
from plakatanima.gui.widgets.plate import PlateLabel
from plakatanima.services.parking import OPERATOR_CAMERA, PlateObservation
from plakatanima.services.registry import VehicleData


def vehicle_type_combo(selected: VehicleType = VehicleType.CAR) -> QComboBox:
    combo = QComboBox()
    for vtype in VehicleType:
        combo.addItem(icon(vtype.icon, vtype.color), vtype.label, vtype)
    combo.setCurrentIndex(max(combo.findData(selected), 0))
    return combo


class PlateInput(QWidget):
    """Plaka giriş alanı + canlı önizleme + yabancı plaka seçeneği."""

    def __init__(self, plate: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.edit = QLineEdit(format_plate(plate) if plate else "")
        self.edit.setPlaceholderText("34 ABC 123")
        self.edit.setMaxLength(14)
        font = self.edit.font()
        font.setPointSizeF(13)
        font.setBold(True)
        self.edit.setFont(font)
        row.addWidget(self.edit, 1)
        self.preview = PlateLabel(height=32)
        row.addWidget(self.preview)
        layout.addLayout(row)
        self.foreign = QCheckBox("Yabancı / özel plaka (format denetimi yapma)")
        layout.addWidget(self.foreign)
        self.hint = muted("")
        layout.addWidget(self.hint)
        self.edit.textChanged.connect(self._update)
        self.foreign.toggled.connect(self._update)
        self._update()

    def _update(self) -> None:
        plate = self.plate()
        self.preview.set_plate(plate or "")
        if not clean_text(self.edit.text()):
            self.hint.setText("Örn: 34 ABC 123, 06 A 1234")
        elif plate is None:
            self.hint.setText("⚠ Geçerli bir Türk plakası değil")
        else:
            parsed = parse_plate(plate, allow_corrections=False)
            self.hint.setText(f"✓ {parsed.province_name}" if parsed else "✓ Yabancı/özel plaka")

    def plate(self) -> str | None:
        text = self.edit.text()
        if self.foreign.isChecked():
            return normalize_plate(text, turkish_only=False, allow_corrections=False)
        parsed = parse_plate(text, allow_corrections=False)
        return parsed.text if parsed else None


class ManualPassDialog(QDialog):
    """Okunamayan araçlar için operatörün elle giriş/çıkış kaydı."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        role: CameraRole = CameraRole.ENTRY,
        plate: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manuel Giriş / Çıkış")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(section_title("Plaka"))
        self.plate_input = PlateInput(plate)
        layout.addWidget(self.plate_input)

        form = QFormLayout()
        self.vehicle_type = vehicle_type_combo()
        form.addRow("Araç tipi", self.vehicle_type)
        direction = QHBoxLayout()
        self.direction = QButtonGroup(self)
        for i, (label, value) in enumerate(
            (("Giriş", CameraRole.ENTRY), ("Çıkış", CameraRole.EXIT))
        ):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(value is role)
            btn.setProperty("role_value", value.value)
            self.direction.addButton(btn, i)
            direction.addWidget(btn)
        self._style_direction()
        self.direction.buttonToggled.connect(lambda *_: self._style_direction())
        form.addRow("Yön", direction)
        layout.addLayout(form)

        buttons = QDialogButtonBox()
        ok = buttons.addButton("Kaydet", QDialogButtonBox.ButtonRole.AcceptRole)
        ok.setProperty("variant", "primary")
        buttons.addButton("Vazgeç", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.observation: PlateObservation | None = None

    def _style_direction(self) -> None:
        palette = theme.current()
        for btn in self.direction.buttons():
            if btn.isChecked():
                btn.setStyleSheet(
                    f"background:{palette.accent}; color:white; border-color:{palette.accent};"
                    "font-weight:600;"
                )
            else:
                btn.setStyleSheet("")

    def _accept(self) -> None:
        plate = self.plate_input.plate()
        if plate is None:
            show_error(self, "Plaka geçerli değil. Yabancı plakalar için kutucuğu işaretleyin.")
            return
        role = CameraRole(self.direction.checkedButton().property("role_value"))
        self.observation = PlateObservation(
            plate=plate,
            camera_name=OPERATOR_CAMERA,
            role=role,
            vehicle_type=enum_data(self.vehicle_type, VehicleType),
            manual=True,
            timestamp=datetime.now(),
        )
        self.accept()


class PaymentDialog(QDialog):
    """Çıkışta ücret tahsilatı (indirim için tutar değiştirilebilir)."""

    def __init__(
        self,
        session: ParkingSession,
        fee: Decimal,
        currency: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ödeme Al")
        self.setMinimumWidth(420)
        self.method: PaymentMethod | None = None
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        head = QHBoxLayout()
        head.addWidget(PlateLabel(session.plate, height=36))
        info = QVBoxLayout()
        info.addWidget(QLabel(f"<b>{session.vehicle_type.label}</b>"))
        info.addWidget(muted(f"Süre: {format_duration(session.duration())}"))
        head.addLayout(info, 1)
        layout.addLayout(head)

        form = QFormLayout()
        form.addRow("Giriş", QLabel(format_datetime(session.entry_time)))
        form.addRow("Çıkış", QLabel(format_datetime(session.exit_time or datetime.now())))
        form.addRow("Tarifeye göre", QLabel(format_money(fee, currency)))
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, 1_000_000)
        self.amount.setDecimals(2)
        self.amount.setSuffix(f" {currency}")
        self.amount.setValue(float(fee))
        font = self.amount.font()
        font.setPointSizeF(14)
        font.setBold(True)
        self.amount.setFont(font)
        form.addRow("Tahsil edilecek", self.amount)
        layout.addLayout(form)

        row = QHBoxLayout()
        for label, method, ico, variant in (
            ("Nakit", PaymentMethod.CASH, "mdi6.cash", "success"),
            ("Kart", PaymentMethod.CARD, "mdi6.credit-card-outline", "primary"),
            ("Ücretsiz", PaymentMethod.FREE, "mdi6.gift-outline", None),
        ):
            btn = button(label, ico, variant=variant)
            btn.clicked.connect(lambda _=False, m=method: self._pay(m))
            row.addWidget(btn)
        layout.addLayout(row)
        later = QPushButton("Daha sonra")
        later.clicked.connect(self.reject)
        layout.addWidget(later, 0, Qt.AlignmentFlag.AlignRight)

    def _pay(self, method: PaymentMethod) -> None:
        self.method = method
        if method is PaymentMethod.FREE:
            self.amount.setValue(0)
        self.accept()

    def amount_value(self) -> Decimal:
        return Decimal(str(round(self.amount.value(), 2)))


class VehicleDialog(QDialog):
    def __init__(self, vehicle: Vehicle | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Araç Düzenle" if vehicle else "Yeni Araç")
        self.setMinimumWidth(480)
        data = VehicleData.from_vehicle(vehicle) if vehicle else VehicleData(plate="")
        self.data: VehicleData | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(section_title("Plaka"))
        self.plate_input = PlateInput(data.plate)
        if data.plate and not parse_plate(data.plate, allow_corrections=False):
            self.plate_input.foreign.setChecked(True)
        layout.addWidget(self.plate_input)

        form = QFormLayout()
        form.setSpacing(8)
        self.vehicle_type = vehicle_type_combo(data.vehicle_type)
        form.addRow("Araç tipi", self.vehicle_type)
        self.owner = QLineEdit(data.owner_name)
        form.addRow("Sahibi / Firma", self.owner)
        self.phone = QLineEdit(data.phone)
        form.addRow("Telefon", self.phone)
        self.brand = QLineEdit(data.brand_model)
        self.brand.setPlaceholderText("Ör. Renault Clio")
        form.addRow("Marka / Model", self.brand)
        self.color = QLineEdit(data.color)
        form.addRow("Renk", self.color)

        self.subscriber = QCheckBox("Abone (ücret alınmaz)")
        self.subscriber.setChecked(data.is_subscriber)
        self.sub_end = QDateEdit()
        self.sub_end.setCalendarPopup(True)
        self.sub_end.setDisplayFormat("dd.MM.yyyy")
        end = data.subscription_end or date(date.today().year, 12, 31)
        self.sub_end.setDate(QDate(end.year, end.month, end.day))
        self.sub_unlimited = QCheckBox("Süresiz")
        self.sub_unlimited.setChecked(data.is_subscriber and data.subscription_end is None)
        sub_row = QHBoxLayout()
        sub_row.addWidget(self.sub_end)
        sub_row.addWidget(self.sub_unlimited)
        form.addRow(self.subscriber)
        form.addRow("Abonelik bitişi", sub_row)

        self.blacklist = QCheckBox("Kara listede (girişte alarm verilir)")
        self.blacklist.setChecked(data.is_blacklisted)
        form.addRow(self.blacklist)
        self.reason = QLineEdit(data.blacklist_reason)
        self.reason.setPlaceholderText("Neden?")
        form.addRow("Kara liste nedeni", self.reason)
        self.notes = QPlainTextEdit(data.notes)
        self.notes.setFixedHeight(70)
        form.addRow("Notlar", self.notes)
        layout.addLayout(form)

        for widget in (self.subscriber, self.sub_unlimited, self.blacklist):
            widget.toggled.connect(self._sync)
        self._sync()

        buttons = QDialogButtonBox()
        ok = buttons.addButton("Kaydet", QDialogButtonBox.ButtonRole.AcceptRole)
        ok.setProperty("variant", "primary")
        buttons.addButton("Vazgeç", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _sync(self) -> None:
        sub = self.subscriber.isChecked()
        self.sub_unlimited.setEnabled(sub)
        self.sub_end.setEnabled(sub and not self.sub_unlimited.isChecked())
        self.reason.setEnabled(self.blacklist.isChecked())

    def _accept(self) -> None:
        plate = self.plate_input.plate()
        if plate is None:
            show_error(self, "Plaka geçerli değil. Yabancı plakalar için kutucuğu işaretleyin.")
            return
        sub = self.subscriber.isChecked()
        end = None
        if sub and not self.sub_unlimited.isChecked():
            end = self.sub_end.date().toPython()
        self.data = VehicleData(
            plate=plate,
            vehicle_type=enum_data(self.vehicle_type, VehicleType),
            owner_name=self.owner.text().strip(),
            phone=self.phone.text().strip(),
            brand_model=self.brand.text().strip(),
            color=self.color.text().strip(),
            is_subscriber=sub,
            subscription_end=end,
            is_blacklisted=self.blacklist.isChecked(),
            blacklist_reason=self.reason.text().strip() if self.blacklist.isChecked() else "",
            notes=self.notes.toPlainText().strip(),
        )
        self.accept()


class _Snapshot(QLabel):
    def __init__(self, path: Path | None, title: str) -> None:
        super().__init__()
        self.setMinimumSize(320, 200)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"background:{theme.current().video_bg}; border-radius:8px;")
        pixmap = QPixmap(str(path)) if path and path.is_file() else QPixmap()
        if pixmap.isNull():
            self.setText(f"{title}\n(görüntü yok)")
        else:
            self.setPixmap(
                pixmap.scaled(
                    480,
                    300,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.setToolTip(str(path))


class SessionDetailDialog(QDialog):
    """Geçiş kaydının ayrıntıları ve anlık görüntüleri."""

    def __init__(
        self,
        session: ParkingSession,
        captures_dir: Path,
        currency: str,
        *,
        current_fee: Decimal | None = None,
        can_delete: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Geçiş Kaydı #{session.id}")
        self.setMinimumWidth(720)
        self.action: str | None = None
        self.new_type: VehicleType | None = None
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        head = QHBoxLayout()
        head.addWidget(PlateLabel(session.plate, height=40))
        title = QVBoxLayout()
        status_color = {
            SessionStatus.OPEN: theme.current().success,
            SessionStatus.CLOSED: theme.current().info,
            SessionStatus.EXIT_MISSED: theme.current().warning,
        }[session.status]
        title.addWidget(QLabel(f"<b style='color:{status_color}'>{session.status.label}</b>"))
        owner = session.vehicle.owner_name if session.vehicle else ""
        title.addWidget(muted(" · ".join(x for x in (session.vehicle_type.label, owner) if x)))
        head.addLayout(title, 1)
        layout.addLayout(head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        rows = [
            (
                "Giriş",
                format_datetime(session.entry_time, with_seconds=True),
                session.entry_camera + (" (manuel)" if session.is_manual_entry else ""),
            ),
            (
                "Çıkış",
                format_datetime(session.exit_time, with_seconds=True),
                session.exit_camera + (" (manuel)" if session.is_manual_exit else ""),
            ),
            ("Süre", format_duration(session.duration()), ""),
        ]
        if session.fee is not None:
            payment = session.payment_method.label if session.payment_method else "Ödenmedi"
            rows.append(("Ücret", format_money(session.fee, currency), payment))
        elif current_fee is not None:
            rows.append(("Biriken ücret", format_money(current_fee, currency), "şu ana kadar"))
        for r, (label, value, extra) in enumerate(rows):
            grid.addWidget(muted(label), r, 0)
            grid.addWidget(QLabel(f"<b>{value}</b>"), r, 1)
            grid.addWidget(muted(extra), r, 2)
        layout.addLayout(grid)

        images = QHBoxLayout()
        for rel, title_text in ((session.entry_image, "Giriş"), (session.exit_image, "Çıkış")):
            box = QVBoxLayout()
            box.addWidget(section_title(title_text))
            box.addWidget(_Snapshot(captures_dir / rel if rel else None, title_text))
            images.addLayout(box)
        layout.addLayout(images)

        actions = QHBoxLayout()
        self.type_combo = vehicle_type_combo(session.vehicle_type)
        actions.addWidget(QLabel("Araç tipi:"))
        actions.addWidget(self.type_combo)
        save_type = button("Tipi Kaydet", "mdi6.content-save-outline")
        save_type.clicked.connect(self._save_type)
        actions.addWidget(save_type)
        actions.addStretch(1)
        if session.status is SessionStatus.OPEN:
            exit_btn = button("Çıkış Yap", "mdi6.logout", variant="primary")
            exit_btn.clicked.connect(lambda: self._finish("exit"))
            actions.addWidget(exit_btn)
        elif session.status is SessionStatus.CLOSED and not session.is_paid:
            pay = button("Ödeme Al", "mdi6.cash-register", variant="success")
            pay.clicked.connect(lambda: self._finish("pay"))
            actions.addWidget(pay)
        if can_delete:
            delete = button("Sil", "mdi6.delete-outline", variant="danger")
            delete.clicked.connect(lambda: self._finish("delete"))
            actions.addWidget(delete)
        close = QPushButton("Kapat")
        close.clicked.connect(self.reject)
        actions.addWidget(close)
        layout.addLayout(actions)

    def _save_type(self) -> None:
        self.new_type = enum_data(self.type_combo, VehicleType)
        self._finish("type")

    def _finish(self, action: str) -> None:
        self.action = action
        self.accept()
