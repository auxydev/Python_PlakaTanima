from __future__ import annotations

import threading
from datetime import datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest
from PySide6.QtWidgets import QLabel

from plakatanima.camera.runner import CameraStatus
from plakatanima.camera.source import Frame
from plakatanima.config import CameraConfig, CameraRole
from plakatanima.context import AppContext
from plakatanima.core.vehicle import VehicleType
from plakatanima.db.models import EventAction, PaymentMethod
from plakatanima.gui import dialogs
from plakatanima.gui.app import build_window
from plakatanima.gui.bridge import CameraBridge
from plakatanima.gui.widgets.camera_view import CameraView
from plakatanima.gui.widgets.table import Column, DataTable, RowModel
from plakatanima.recognition.types import (
    BBox,
    FrameAnalysis,
    PlateRead,
    VehicleDetection,
)
from plakatanima.services.parking import PlateObservation


@pytest.fixture
def ctx():
    context = AppContext.create()
    yield context
    context.close()


@pytest.fixture
def window(qtbot, ctx):
    win = build_window(ctx, start_cameras=False)
    qtbot.addWidget(win)
    win.show()
    yield win
    win.controller.shutdown()


def test_all_pages_open(window):
    for key, page in window.pages.items():
        window.show_page(key)
        assert window.stack.currentWidget() is page
    assert set(window.pages) == {
        "dashboard",
        "inside",
        "sessions",
        "vehicles",
        "tariffs",
        "settings",
    }


def test_plate_flow_updates_pages(window, ctx):
    controller = window.controller
    dashboard = window.pages["dashboard"]
    inside = window.pages["inside"]
    before = dashboard.feed.count()

    entry_time = datetime.now() - timedelta(hours=2)
    result = controller.process(
        PlateObservation(
            "34ABC123", "Giriş", CameraRole.ENTRY, VehicleType.CAR, timestamp=entry_time
        )
    )
    assert result.action is EventAction.ENTRY
    assert dashboard.feed.count() == before + 1
    assert [s.plate for s in inside.model.rows()] == ["34ABC123"]
    assert dashboard.occupancy.value.text() == "1 / 100"

    result = controller.process(PlateObservation("34ABC123", "Çıkış", CameraRole.EXIT))
    assert result.needs_payment
    assert inside.model.rows() == []
    assert controller.toasts._toasts  # ödeme bildirimi gösterildi

    ctx.parking.record_payment(result.session_id, PaymentMethod.CASH)
    controller.data_changed.emit()
    sessions = window.pages["sessions"]
    assert sessions.model.rows()[0].is_paid
    assert dashboard.revenue.value.text() == "90,00 TL"


def test_blacklist_alert_toast(window, ctx):
    from plakatanima.services.registry import VehicleData

    ctx.vehicles.save(VehicleData(plate="06BAD01", is_blacklisted=True, blacklist_reason="test"))
    window.controller.data_changed.emit()
    result = window.controller.process(PlateObservation("06BAD01", "Giriş", CameraRole.ENTRY))
    assert result.is_blacklisted
    texts = [
        label.text()
        for toast in window.controller.toasts._toasts
        for label in toast.findChildren(QLabel)
    ]
    assert "KARA LİSTE ARACI" in texts
    assert window.pages["vehicles"].model.rowCount() == 1


def test_bridge_coalesces_frames(qtbot):
    bridge = CameraBridge()
    received = []
    bridge.frame_ready.connect(lambda index, image: received.append(int(image[0, 0, 0])))

    def produce():
        for i in range(50):
            bridge._on_frame(0, Frame(np.full((4, 4, 3), i, np.uint8), index=i))

    thread = threading.Thread(target=produce)
    thread.start()
    thread.join()
    qtbot.waitUntil(lambda: bool(received) and received[-1] == 49, timeout=2000)
    assert len(received) < 50


def test_camera_view_renders(qtbot):
    view = CameraView(0, CameraConfig(name="Test", roi=(0.0, 0.2, 1.0, 1.0)))
    qtbot.addWidget(view)
    view.resize(640, 420)
    view.show()
    view.set_status(CameraStatus.RUNNING, "")
    view.set_frame(np.zeros((360, 640, 3), np.uint8))
    vehicle = VehicleDetection(BBox(100, 100, 300, 300), VehicleType.TRUCK, 0.9)
    analysis = FrameAnalysis(
        vehicles=[vehicle],
        plates=[PlateRead(BBox(150, 260, 230, 280), "34ABC123", "34ABC123", 0.95, vehicle)],
    )
    view.set_analysis(analysis)
    image = view.grab().toImage()
    assert not image.isNull()
    assert "fps" in view.stats_label.text()
    view.set_status(CameraStatus.ERROR, "bağlantı yok")
    assert view.status_label.text() == "Hata"


def test_manual_pass_dialog(qtbot, monkeypatch):
    errors = []
    monkeypatch.setattr(dialogs, "show_error", lambda parent, text: errors.append(text))
    dialog = dialogs.ManualPassDialog(role=CameraRole.EXIT)
    qtbot.addWidget(dialog)
    dialog.plate_input.edit.setText("34 abç 12")  # geçersiz (Ç -> C, 3 harf + 2 rakam geçerli)
    dialog._accept()
    assert dialog.observation is not None
    assert dialog.observation.plate == "34ABC12"
    assert dialog.observation.role is CameraRole.EXIT
    assert dialog.observation.manual

    dialog.observation = None
    dialog.plate_input.edit.setText("ABC")
    dialog._accept()
    assert dialog.observation is None
    assert errors

    dialog.plate_input.foreign.setChecked(True)
    dialog.plate_input.edit.setText("B MW 1234")
    dialog._accept()
    assert dialog.observation.plate == "BMW1234"


def test_vehicle_dialog_builds_data(qtbot):
    dialog = dialogs.VehicleDialog()
    qtbot.addWidget(dialog)
    dialog.plate_input.edit.setText("06 AB 1234")
    dialog.owner.setText("Ali Veli")
    dialog.subscriber.setChecked(True)
    dialog.sub_unlimited.setChecked(True)
    dialog.vehicle_type.setCurrentIndex(dialog.vehicle_type.findData(VehicleType.BUS))
    dialog._accept()
    data = dialog.data
    assert data.plate == "06AB1234"
    assert data.owner_name == "Ali Veli"
    assert data.is_subscriber and data.subscription_end is None
    assert data.vehicle_type is VehicleType.BUS


def test_payment_dialog_amount(qtbot, ctx):
    ctx.parking.process(PlateObservation("35A1234", timestamp=datetime.now() - timedelta(hours=1)))
    result = ctx.parking.process(PlateObservation("35A1234", role=CameraRole.EXIT))
    session = ctx.parking.get_session(result.session_id)
    dialog = dialogs.PaymentDialog(session, session.fee, "TL")
    qtbot.addWidget(dialog)
    dialog.amount.setValue(50)
    dialog._pay(PaymentMethod.CARD)
    assert dialog.method is PaymentMethod.CARD
    assert dialog.amount_value() == Decimal("50.0")


def test_settings_page_saves_config(window, ctx, monkeypatch):
    from plakatanima.gui.pages import settings as settings_module

    monkeypatch.setattr(settings_module, "confirm", lambda *a, **k: False)
    page = window.pages["settings"]
    page.capacity.setValue(250)
    page.lot_name.setText("Merkez Otopark")
    page.min_hits.setValue(4)
    page._add_camera()
    page.editor.name.setText("Arka Kapı")
    page.editor.role.setCurrentIndex(page.editor.role.findData(CameraRole.BOTH))
    page.save()
    assert ctx.config.parking.capacity == 250
    assert ctx.config.recognition.min_hits == 4
    assert [c.name for c in ctx.config.cameras][-1] == "Arka Kapı"
    assert ctx.config.cameras[-1].role is CameraRole.BOTH
    saved = ctx.config_path.read_text(encoding="utf-8")
    assert "Merkez Otopark" in saved
    assert "Arka Kapı" in saved


def test_tariffs_page_saves(window, ctx):
    page = window.pages["tariffs"]
    row = page.rows[VehicleType.MOTORCYCLE]
    row.first.setValue(42)
    page.save()
    tariff = next(t for t in ctx.tariffs.all() if t.vehicle_type is VehicleType.MOTORCYCLE)
    assert tariff.first_hour_fee == Decimal("42.00")
    page.calc_type.setCurrentIndex(page.calc_type.findData(VehicleType.MOTORCYCLE))
    page.calc_hours.setValue(0)
    page.calc_minutes.setValue(30)
    assert page.calc_result.text() == "42,00 TL"


def test_data_table_sorting(qtbot):
    rows = [{"p": "34A1111", "n": 3}, {"p": "06B2222", "n": 10}, {"p": "35C3333", "n": 1}]
    model = RowModel([Column("Plaka", lambda r: r["p"]), Column("N", str, sort=lambda r: r["n"])])
    model.set_rows(rows)
    table = DataTable(model)
    qtbot.addWidget(table)
    # varsayılan: kaynak sırası
    assert table.row_for_index(table.proxy.index(0, 0))["p"] == "34A1111"
    model.columns[1].text = lambda r: str(r["n"])
    table.sortByColumn(1, __import__("PySide6.QtCore").QtCore.Qt.SortOrder.AscendingOrder)
    assert [table.row_for_index(table.proxy.index(i, 0))["n"] for i in range(3)] == [1, 3, 10]
