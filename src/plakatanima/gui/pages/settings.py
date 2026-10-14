"""Ayarlar: genel, kameralar, tanıma."""

from __future__ import annotations

import threading
from pathlib import Path

from pydantic import ValidationError
from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from plakatanima.camera.snapshot import cleanup_snapshots
from plakatanima.camera.source import OpenCVSource, SourceError, describe_source
from plakatanima.config import AppConfig, CameraConfig, CameraRole
from plakatanima.gui import theme
from plakatanima.gui.controller import Controller
from plakatanima.gui.utils import (
    Card,
    bgr_to_qimage,
    button,
    confirm,
    enum_data,
    icon,
    muted,
    page_header,
    section_title,
    show_error,
)
from plakatanima.recognition.model_store import YOLOX_MODELS
from plakatanima.services.maintenance import (
    DEFAULT_KEEP,
    BackupError,
    backup_database,
    list_backups,
)

PLATE_DETECTORS = (
    "yolo-v9-t-384-license-plate-end2end",
    "yolo-v9-t-512-license-plate-end2end",
    "yolo-v9-t-640-license-plate-end2end",
    "yolo-v9-s-608-license-plate-end2end",
)
OCR_MODELS = (
    "cct-xs-v2-global-model",
    "cct-s-v2-global-model",
    "global-plates-mobile-vit-v2-model",
)


def _spin(minimum: int, maximum: int, suffix: str = "") -> QSpinBox:
    box = QSpinBox()
    box.setRange(minimum, maximum)
    if suffix:
        box.setSuffix(suffix)
    return box


def _dspin(minimum: float, maximum: float, step: float, decimals: int = 2) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setSingleStep(step)
    box.setDecimals(decimals)
    return box


def _open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def _scroll(widget: QWidget) -> QScrollArea:
    widget.setMaximumWidth(860)
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 8, 0, 0)
    layout.addWidget(widget, 1)
    layout.addStretch(0)
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(holder)
    return area


class _TestSignals(QObject):
    done = Signal(object, str)  # np.ndarray | None, mesaj


class CameraEditor(QWidget):
    """Seçili kameranın ayarları."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        form = QFormLayout(self)
        form.setSpacing(10)
        self.name = QLineEdit()
        form.addRow("Kamera adı", self.name)

        source_row = QHBoxLayout()
        self.source = QComboBox()
        self.source.setEditable(True)
        self.source.addItems(["0", "1", "demo", "rtsp://kullanici:sifre@192.168.1.64:554/stream1"])
        self.source.setToolTip("Webcam numarası, RTSP/HTTP adresi, video dosyası veya 'demo'")
        source_row.addWidget(self.source, 1)
        browse = button("", "mdi6.folder-open-outline", tooltip="Video dosyası seç")
        browse.clicked.connect(self._browse)
        source_row.addWidget(browse)
        form.addRow("Kaynak", source_row)
        form.addRow("", muted("Webcam: 0, 1 …  ·  IP kamera: rtsp://…  ·  Dosya: .mp4  ·  demo"))

        self.role = QComboBox()
        for role in CameraRole:
            self.role.addItem(role.label, role)
        form.addRow("Görev", self.role)
        self.enabled = QCheckBox("Etkin")
        form.addRow("", self.enabled)
        self.fps = _dspin(0.5, 30, 0.5, 1)
        self.fps.setSuffix(" kare/sn")
        self.fps.setToolTip("Saniyede kaç karenin tanıma için işleneceği")
        form.addRow("Analiz hızı", self.fps)

        self.use_roi = QCheckBox("Yalnızca belirli bir bölgeyi işle (ROI)")
        form.addRow("", self.use_roi)
        roi_row = QHBoxLayout()
        self.roi = [_dspin(0, 1, 0.05) for _ in range(4)]
        for label, box in zip(("x1", "y1", "x2", "y2"), self.roi, strict=True):
            roi_row.addWidget(QLabel(label))
            roi_row.addWidget(box)
        form.addRow("Bölge (0-1)", roi_row)
        self.use_roi.toggled.connect(lambda on: [b.setEnabled(on) for b in self.roi])

        test_row = QHBoxLayout()
        self.test_btn = button("Bağlantıyı Test Et", "mdi6.connection")
        self.test_btn.clicked.connect(self._test)
        test_row.addWidget(self.test_btn)
        self.test_result = muted("")
        self.test_result.setWordWrap(True)
        test_row.addWidget(self.test_result, 1)
        form.addRow("", test_row)
        self.preview = QLabel()
        self.preview.setFixedHeight(200)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet(f"background:{theme.current().video_bg}; border-radius:8px;")
        form.addRow("", self.preview)

        self._signals = _TestSignals()
        self._signals.done.connect(self._test_done)
        for widget in (self.name, self.source.lineEdit()):
            widget.textChanged.connect(lambda *_: self.changed.emit())
        self.role.currentIndexChanged.connect(lambda *_: self.changed.emit())
        self.enabled.toggled.connect(lambda *_: self.changed.emit())

    def load(self, camera: CameraConfig) -> None:
        self.name.setText(camera.name)
        self.source.setCurrentText(camera.source)
        self.role.setCurrentIndex(self.role.findData(camera.role))
        self.enabled.setChecked(camera.enabled)
        self.fps.setValue(camera.process_fps)
        roi = camera.roi or (0.0, 0.0, 1.0, 1.0)
        self.use_roi.setChecked(camera.roi is not None)
        for box, value in zip(self.roi, roi, strict=True):
            box.setValue(value)
            box.setEnabled(camera.roi is not None)
        self.preview.clear()
        self.test_result.setText("")

    def to_config(self) -> CameraConfig:
        roi = tuple(b.value() for b in self.roi) if self.use_roi.isChecked() else None
        return CameraConfig(
            name=self.name.text().strip() or "Kamera",
            source=self.source.currentText().strip(),
            role=enum_data(self.role, CameraRole),
            enabled=self.enabled.isChecked(),
            process_fps=self.fps.value(),
            roi=roi,
        )

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Video dosyası", "", "Video (*.mp4 *.avi *.mkv *.mov);;Tüm dosyalar (*)"
        )
        if path:
            self.source.setCurrentText(path)

    def _test(self) -> None:
        source = self.source.currentText().strip()
        if source.lower() == "demo":
            self.test_result.setText("Demo kaynağı kamera gerektirmez.")
            return
        self.test_btn.setEnabled(False)
        self.test_result.setText(f"{describe_source(source)} açılıyor…")

        def worker() -> None:
            capture = OpenCVSource(source, loop=False)
            try:
                capture.open()
                frame = capture.read()
                if frame is None:
                    self._signals.done.emit(None, "Bağlandı ama görüntü alınamadı.")
                else:
                    h, w = frame.image.shape[:2]
                    self._signals.done.emit(frame.image, f"✓ Bağlantı başarılı ({w}×{h})")
            except SourceError as exc:
                self._signals.done.emit(None, f"✗ {exc}")
            finally:
                capture.close()

        threading.Thread(target=worker, daemon=True, name="camera-test").start()

    def _test_done(self, image, message: str) -> None:
        self.test_btn.setEnabled(True)
        self.test_result.setText(message)
        if image is not None:
            pixmap = QPixmap.fromImage(bgr_to_qimage(image))
            self.preview.setPixmap(
                pixmap.scaledToHeight(200, Qt.TransformationMode.SmoothTransformation)
            )


class SettingsPage(QWidget):
    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageRoot")
        self.controller = controller
        self.ctx = controller.ctx

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)
        save = button("Kaydet", "mdi6.content-save-outline", variant="primary")
        save.clicked.connect(self.save)
        revert = button("Geri Al", "mdi6.undo")
        revert.clicked.connect(self.load)
        root.addWidget(
            page_header("Ayarlar", f"Ayar dosyası: {self.ctx.config_path}", [revert, save])
        )

        self.tabs = QTabWidget()
        self.tabs.addTab(_scroll(self._general_tab()), icon("mdi6.tune"), "Genel")
        self.tabs.addTab(self._cameras_tab(), icon("mdi6.cctv"), "Kameralar")
        self.tabs.addTab(_scroll(self._recognition_tab()), icon("mdi6.eye-outline"), "Tanıma")
        self.tabs.addTab(
            _scroll(self._maintenance_tab()), icon("mdi6.database-cog-outline"), "Bakım"
        )
        root.addWidget(self.tabs, 1)
        self.load()

    # ---------------------------------------------------------------- genel
    def _general_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        card = Card()
        card.body.addWidget(section_title("Otopark"))
        form = QFormLayout()
        form.setSpacing(10)
        self.lot_name = QLineEdit()
        form.addRow("Otopark adı", self.lot_name)
        self.capacity = _spin(1, 100_000, " araç")
        form.addRow("Kapasite", self.capacity)
        self.currency = QLineEdit()
        self.currency.setMaximumWidth(80)
        form.addRow("Para birimi", self.currency)
        self.min_stay = _spin(0, 3600, " sn")
        self.min_stay.setToolTip(
            "Aynı plakanın bu süre içinde tekrar okunması yeni bir geçiş sayılmaz"
        )
        form.addRow("Tekrar okuma süresi", self.min_stay)
        card.body.addLayout(form)
        layout.addWidget(card)

        card = Card()
        card.body.addWidget(section_title("Görüntüler ve arayüz"))
        form = QFormLayout()
        form.setSpacing(10)
        self.save_snapshots = QCheckBox("Giriş/çıkış anlık görüntülerini kaydet")
        form.addRow("", self.save_snapshots)
        self.retention = _spin(1, 3650, " gün")
        form.addRow("Görüntü saklama süresi", self.retention)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Koyu", "dark")
        self.theme_combo.addItem("Açık", "light")
        form.addRow("Tema (yeniden başlatınca)", self.theme_combo)
        self.events_limit = _spin(5, 500, " kayıt")
        form.addRow("Son geçişler listesi", self.events_limit)
        self.require_login = QCheckBox("Açılışta kullanıcı girişi iste")
        form.addRow("", self.require_login)
        card.body.addLayout(form)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------ kameralar
    def _cameras_tab(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        left = Card(padding=10)
        self.camera_list = QListWidget()
        self.camera_list.setMinimumWidth(230)
        left.body.addWidget(self.camera_list, 1)
        row = QHBoxLayout()
        add = button("Ekle", "mdi6.plus")
        add.clicked.connect(self._add_camera)
        remove = button("Sil", "mdi6.delete-outline", variant="danger")
        remove.clicked.connect(self._remove_camera)
        row.addWidget(add)
        row.addWidget(remove)
        left.body.addLayout(row)
        layout.addWidget(left, 1)

        right = Card()
        self.editor = CameraEditor()
        right.body.addWidget(self.editor)
        right.body.addStretch(1)
        layout.addWidget(right, 2)

        self._cameras: list[CameraConfig] = []
        self._current_row = -1
        self.camera_list.currentRowChanged.connect(self._select_camera)
        self.editor.changed.connect(self._editor_changed)
        return page

    def _refresh_camera_list(self) -> None:
        self.camera_list.blockSignals(True)
        self.camera_list.clear()
        for camera in self._cameras:
            item = QListWidgetItem(
                icon("mdi6.cctv"),
                f"{camera.name}\n{camera.role.label} · {describe_source(camera.source)}",
            )
            if not camera.enabled:
                item.setForeground(Qt.GlobalColor.gray)
            self.camera_list.addItem(item)
        self.camera_list.blockSignals(False)

    def _select_camera(self, row: int) -> None:
        self._store_current()
        self._current_row = row
        self.editor.setEnabled(row >= 0)
        if 0 <= row < len(self._cameras):
            self.editor.load(self._cameras[row])

    def _store_current(self) -> bool:
        if 0 <= self._current_row < len(self._cameras):
            try:
                self._cameras[self._current_row] = self.editor.to_config()
            except ValidationError as exc:
                show_error(self, f"Kamera ayarı geçersiz:\n{exc}")
                return False
        return True

    def _editor_changed(self) -> None:
        row = self._current_row
        if 0 <= row < len(self._cameras):
            try:
                camera = self.editor.to_config()
            except ValidationError:
                return
            item = self.camera_list.item(row)
            if item is not None:
                item.setText(
                    f"{camera.name}\n{camera.role.label} · {describe_source(camera.source)}"
                )

    def _add_camera(self) -> None:
        self._store_current()
        role = CameraRole.EXIT if self._cameras else CameraRole.ENTRY
        name = "Çıkış Kamerası" if role is CameraRole.EXIT else "Giriş Kamerası"
        self._cameras.append(CameraConfig(name=name, source="0", role=role))
        self._current_row = -1
        self._refresh_camera_list()
        self.camera_list.setCurrentRow(len(self._cameras) - 1)

    def _remove_camera(self) -> None:
        row = self.camera_list.currentRow()
        if row < 0 or not confirm(self, "Kamerayı sil", f"{self._cameras[row].name} silinsin mi?"):
            return
        self._cameras.pop(row)
        self._current_row = -1
        self._refresh_camera_list()
        self.camera_list.setCurrentRow(min(row, len(self._cameras) - 1))

    # --------------------------------------------------------------- tanıma
    def _recognition_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        card = Card()
        card.body.addWidget(section_title("Araç tespiti ve sınıflandırma"))
        form = QFormLayout()
        form.setSpacing(10)
        self.detector = QComboBox()
        self.detector.addItem("YOLOX (ONNX, önerilen)", "yolox")
        self.detector.addItem("Ultralytics YOLO (.pt, opsiyonel)", "ultralytics")
        self.detector.addItem("Kapalı (araç tipi tespit edilmez)", "none")
        form.addRow("Yöntem", self.detector)
        model_row = QHBoxLayout()
        self.vehicle_model = QComboBox()
        self.vehicle_model.setEditable(True)
        for name, spec in YOLOX_MODELS.items():
            self.vehicle_model.addItem(name)
            self.vehicle_model.setItemData(
                self.vehicle_model.count() - 1, spec.description, Qt.ItemDataRole.ToolTipRole
            )
        self.vehicle_model.addItems(["yolo11n.pt", "yolo11s.pt"])
        model_row.addWidget(self.vehicle_model, 1)
        browse = button("", "mdi6.folder-open-outline", tooltip="Model dosyası seç")
        browse.clicked.connect(self._browse_model)
        model_row.addWidget(browse)
        form.addRow("Model", model_row)
        form.addRow("", muted(" · ".join(f"{n}: {s.description}" for n, s in YOLOX_MODELS.items())))
        self.vehicle_conf = _dspin(0.05, 0.99, 0.05)
        form.addRow("Araç güven eşiği", self.vehicle_conf)
        card.body.addLayout(form)
        layout.addWidget(card)

        card = Card()
        card.body.addWidget(section_title("Plaka okuma"))
        form = QFormLayout()
        form.setSpacing(10)
        self.plate_detector = QComboBox()
        self.plate_detector.addItems(PLATE_DETECTORS)
        form.addRow("Plaka dedektörü", self.plate_detector)
        self.plate_conf = _dspin(0.05, 0.99, 0.05)
        form.addRow("Plaka tespit eşiği", self.plate_conf)
        self.ocr_model = QComboBox()
        self.ocr_model.addItems(OCR_MODELS)
        form.addRow("OCR modeli", self.ocr_model)
        self.ocr_conf = _dspin(0.0, 1.0, 0.05)
        form.addRow("En düşük OCR güveni", self.ocr_conf)
        self.turkish_only = QCheckBox("Yalnızca Türk plaka formatını kabul et")
        form.addRow("", self.turkish_only)
        card.body.addLayout(form)
        layout.addWidget(card)

        card = Card()
        card.body.addWidget(section_title("Onaylama"))
        form = QFormLayout()
        form.setSpacing(10)
        self.min_hits = _spin(1, 50, " okuma")
        self.min_hits.setToolTip("Bir plakanın onaylanması için kaç karede okunması gerektiği")
        form.addRow("Gereken okuma sayısı", self.min_hits)
        self.track_timeout = _dspin(0.5, 30, 0.5, 1)
        self.track_timeout.setSuffix(" sn")
        form.addRow("İz zaman aşımı", self.track_timeout)
        self.cooldown = _dspin(0, 3600, 5, 0)
        self.cooldown.setSuffix(" sn")
        form.addRow("Aynı plaka bekleme süresi", self.cooldown)
        self.device = QComboBox()
        self.device.addItem("Otomatik (GPU varsa kullan)", "auto")
        self.device.addItem("İşlemci (CPU)", "cpu")
        self.device.addItem("NVIDIA GPU (CUDA)", "cuda")
        form.addRow("Donanım", self.device)
        card.body.addLayout(form)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    # ---------------------------------------------------------------- bakım
    def _maintenance_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        card = Card()
        card.body.addWidget(section_title("Veritabanı yedekleri"))
        card.body.addWidget(
            muted(
                "Uygulama her açılışta, son yedek bir günden eskiyse otomatik yedek alır. "
                f"En son {DEFAULT_KEEP} yedek saklanır."
            )
        )
        self.backup_list = QListWidget()
        self.backup_list.setMaximumHeight(170)
        card.body.addWidget(self.backup_list)
        row = QHBoxLayout()
        backup_now = button("Şimdi Yedekle", "mdi6.database-export-outline", variant="primary")
        backup_now.clicked.connect(self._backup_now)
        row.addWidget(backup_now)
        open_backups = button("Klasörü Aç", "mdi6.folder-open-outline")
        open_backups.clicked.connect(lambda: _open_folder(self.ctx.paths.backups_dir))
        row.addWidget(open_backups)
        row.addStretch(1)
        card.body.addLayout(row)
        layout.addWidget(card)

        card = Card()
        card.body.addWidget(section_title("Anlık görüntüler"))
        self.captures_info = muted("")
        card.body.addWidget(self.captures_info)
        row = QHBoxLayout()
        clean = button("Eski Görüntüleri Temizle", "mdi6.broom")
        clean.clicked.connect(self._clean_snapshots)
        row.addWidget(clean)
        open_captures = button("Klasörü Aç", "mdi6.folder-open-outline")
        open_captures.clicked.connect(lambda: _open_folder(self.ctx.paths.captures_dir))
        row.addWidget(open_captures)
        row.addStretch(1)
        card.body.addLayout(row)
        layout.addWidget(card)

        card = Card()
        card.body.addWidget(section_title("Dosya konumları"))
        form = QFormLayout()
        db_url = self.ctx.db.engine.url.render_as_string(hide_password=True)
        for label, value in (
            ("Ayar dosyası", str(self.ctx.config_path)),
            ("Veri dizini", str(self.ctx.paths.data_dir)),
            ("Veritabanı", db_url),
            ("Modeller", str(self.ctx.paths.models_dir)),
            ("Loglar", str(self.ctx.paths.logs_dir)),
        ):
            text = QLabel(value)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            text.setWordWrap(True)
            form.addRow(label, text)
        card.body.addLayout(form)
        open_data = button("Veri Dizinini Aç", "mdi6.folder-open-outline")
        open_data.clicked.connect(lambda: _open_folder(self.ctx.paths.data_dir))
        card.body.addWidget(open_data, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _refresh_maintenance(self) -> None:
        self.backup_list.clear()
        for info in list_backups(self.ctx.paths.backups_dir):
            self.backup_list.addItem(
                QListWidgetItem(
                    icon("mdi6.database-outline"),
                    f"{info.created:%d.%m.%Y %H:%M}   ·   {info.size / 1_048_576:.1f} MB   ·   "
                    f"{info.path.name}",
                )
            )
        if not self.backup_list.count():
            self.backup_list.addItem("Henüz yedek yok")
        files = list(self.ctx.paths.captures_dir.rglob("*.jpg"))
        size = sum(f.stat().st_size for f in files) / 1_048_576
        days = self.ctx.config.parking.snapshot_retention_days
        self.captures_info.setText(
            f"{len(files)} görüntü, {size:.1f} MB · {days} günden eski görüntüler otomatik silinir."
        )

    def _backup_now(self) -> None:
        try:
            path = backup_database(self.ctx.db, self.ctx.paths.backups_dir)
        except (BackupError, OSError) as exc:
            show_error(self, str(exc))
            return
        self.controller.toast("Yedek alındı", path.name, "success")
        self._refresh_maintenance()

    def _clean_snapshots(self) -> None:
        days = self.ctx.config.parking.snapshot_retention_days
        removed = cleanup_snapshots(self.ctx.paths.captures_dir, days)
        self.controller.toast("Temizlik tamamlandı", f"{removed} görüntü silindi", "success")
        self._refresh_maintenance()

    def _browse_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Model dosyası", "", "Modeller (*.onnx *.pt);;Tüm dosyalar (*)"
        )
        if path:
            self.vehicle_model.setCurrentText(path)

    # ---------------------------------------------------------- yükle/kaydet
    def load(self) -> None:
        cfg = self.ctx.config
        self.lot_name.setText(cfg.parking.lot_name)
        self.capacity.setValue(cfg.parking.capacity)
        self.currency.setText(cfg.parking.currency)
        self.min_stay.setValue(cfg.parking.min_stay_seconds)
        self.save_snapshots.setChecked(cfg.parking.save_snapshots)
        self.retention.setValue(cfg.parking.snapshot_retention_days)
        self.theme_combo.setCurrentIndex(self.theme_combo.findData(cfg.ui.theme))
        self.events_limit.setValue(cfg.ui.recent_events_limit)
        self.require_login.setChecked(cfg.ui.require_login)

        rec = cfg.recognition
        self.detector.setCurrentIndex(self.detector.findData(rec.vehicle_detector))
        self.vehicle_model.setCurrentText(rec.vehicle_model)
        self.vehicle_conf.setValue(rec.vehicle_confidence)
        self.plate_detector.setCurrentText(rec.plate_detector_model)
        self.plate_conf.setValue(rec.plate_detector_confidence)
        self.ocr_model.setCurrentText(rec.ocr_model)
        self.ocr_conf.setValue(rec.min_ocr_confidence)
        self.turkish_only.setChecked(rec.turkish_plates_only)
        self.min_hits.setValue(rec.min_hits)
        self.track_timeout.setValue(rec.track_timeout_seconds)
        self.cooldown.setValue(rec.cooldown_seconds)
        self.device.setCurrentIndex(self.device.findData(rec.device))

        self._refresh_maintenance()
        self._cameras = [c.model_copy() for c in cfg.cameras]
        self._current_row = -1
        self._refresh_camera_list()
        if self._cameras:
            self.camera_list.setCurrentRow(0)
        else:
            self.editor.setEnabled(False)

    def build_config(self) -> AppConfig:
        """Formdaki değerlerden yeni bir ayar nesnesi (doğrulanmış) üretir."""
        if not self._store_current():
            raise ValueError("Kamera ayarları geçersiz")
        data = self.ctx.config.model_dump()
        data["parking"].update(
            lot_name=self.lot_name.text().strip() or "Otopark",
            capacity=self.capacity.value(),
            currency=self.currency.text().strip() or "TL",
            min_stay_seconds=self.min_stay.value(),
            save_snapshots=self.save_snapshots.isChecked(),
            snapshot_retention_days=self.retention.value(),
        )
        data["ui"].update(
            theme=self.theme_combo.currentData(),
            recent_events_limit=self.events_limit.value(),
            require_login=self.require_login.isChecked(),
        )
        data["recognition"].update(
            vehicle_detector=self.detector.currentData(),
            vehicle_model=self.vehicle_model.currentText().strip(),
            vehicle_confidence=self.vehicle_conf.value(),
            plate_detector_model=self.plate_detector.currentText(),
            plate_detector_confidence=self.plate_conf.value(),
            ocr_model=self.ocr_model.currentText(),
            min_ocr_confidence=self.ocr_conf.value(),
            turkish_plates_only=self.turkish_only.isChecked(),
            min_hits=self.min_hits.value(),
            track_timeout_seconds=self.track_timeout.value(),
            cooldown_seconds=self.cooldown.value(),
            device=self.device.currentData(),
        )
        data["cameras"] = [c.model_dump() for c in self._cameras]
        return AppConfig.model_validate(data)

    def save(self) -> None:
        try:
            new = self.build_config()
        except (ValidationError, ValueError) as exc:
            show_error(self, f"Ayarlar kaydedilemedi:\n{exc}")
            return
        cfg = self.ctx.config
        restart_needed = (
            new.cameras != cfg.cameras
            or new.recognition.model_dump(include=_RESTART_FIELDS)
            != cfg.recognition.model_dump(include=_RESTART_FIELDS)
            or new.parking.save_snapshots != cfg.parking.save_snapshots
        )
        # Servisler aynı ayar nesnelerini kullandığı için alanlar yerinde güncellenir.
        for section in ("parking", "recognition", "ui", "database"):
            target = getattr(cfg, section)
            for name, value in getattr(new, section):
                setattr(target, name, value)
        cfg.cameras = new.cameras
        self.ctx.save_config()
        self.controller.data_changed.emit()
        self.controller.toast("Ayarlar kaydedildi", str(self.ctx.config_path), "success")
        if restart_needed and confirm(
            self,
            "Kameralar",
            "Kamera veya model ayarları değişti. Kameralar yeniden başlatılsın mı?",
        ):
            self.controller.start_cameras()
        self.load()


# Bu alanlar kameralar başlatılırken modellere/oylayıcıya aktarılır; değişince yeniden başlatılmalı.
_RESTART_FIELDS = {
    "vehicle_detector",
    "vehicle_model",
    "vehicle_confidence",
    "plate_detector_model",
    "plate_detector_confidence",
    "ocr_model",
    "device",
    "min_hits",
    "track_timeout_seconds",
    "cooldown_seconds",
}
