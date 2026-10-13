"""Raporlar: dönem özeti, grafikler ve Excel/CSV dışa aktarma."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QDate, QTimer
from PySide6.QtWidgets import (
    QDateEdit,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from plakatanima.core.formatting import format_duration, format_money
from plakatanima.gui import theme
from plakatanima.gui.controller import Controller
from plakatanima.gui.utils import Card, button, muted, page_header, section_title, show_error
from plakatanima.gui.widgets.cards import StatCard
from plakatanima.gui.widgets.charts import (
    BarItem,
    BarListChart,
    ColumnChart,
    Series,
    compact,
    entry_color,
    exit_color,
    series_color,
    vehicle_color,
)
from plakatanima.services.reports import (
    export_sessions_csv,
    export_sessions_xlsx,
    sessions_for_export,
)


def _qdate(value: date) -> QDate:
    return QDate(value.year, value.month, value.day)


def _chart_card(title: str, subtitle: str, chart: QWidget) -> Card:
    card = Card(padding=14)
    head = QHBoxLayout()
    head.addWidget(section_title(title))
    head.addStretch(1)
    if subtitle:
        head.addWidget(muted(subtitle))
    card.body.addLayout(head)
    card.body.addWidget(chart, 1)
    return card


class ReportsPage(QWidget):
    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageRoot")
        self.controller = controller
        self.ctx = controller.ctx
        palette = theme.current()
        self.currency = self.ctx.config.parking.currency

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        content = QWidget()
        content.setObjectName("PageRoot")
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        excel = button("Excel'e Aktar", "mdi6.microsoft-excel", variant="primary")
        excel.clicked.connect(lambda: self.export("xlsx"))
        csv_btn = button("CSV", "mdi6.file-delimited-outline")
        csv_btn.clicked.connect(lambda: self.export("csv"))
        root.addWidget(
            page_header("Raporlar", "Seçilen döneme ait trafik ve gelir özeti", [csv_btn, excel])
        )

        filters = QHBoxLayout()
        today = date.today()
        self.start = QDateEdit(_qdate(today - timedelta(days=13)))
        self.end = QDateEdit(_qdate(today))
        for edit in (self.start, self.end):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("dd.MM.yyyy")
        filters.addWidget(QLabel("Dönem"))
        filters.addWidget(self.start)
        filters.addWidget(QLabel("–"))
        filters.addWidget(self.end)
        for label, days in (("Bugün", 0), ("7 gün", 6), ("14 gün", 13), ("30 gün", 29)):
            quick = QPushButton(label)
            quick.clicked.connect(lambda _=False, d=days: self._quick(d))
            filters.addWidget(quick)
        this_month = QPushButton("Bu ay")
        this_month.clicked.connect(self._this_month)
        filters.addWidget(this_month)
        filters.addStretch(1)
        root.addLayout(filters)

        kpis = QHBoxLayout()
        kpis.setSpacing(14)
        self.kpi_entries = StatCard("Toplam giriş", "mdi6.car-arrow-right", palette.success)
        self.kpi_revenue = StatCard("Tahsilat", "mdi6.cash-multiple", palette.warning)
        self.kpi_stay = StatCard("Ortalama kalış", "mdi6.timer-outline", palette.info)
        self.kpi_unique = StatCard(
            "Tekil araç", "mdi6.card-account-details-outline", palette.accent
        )
        self.kpi_unpaid = StatCard("Ödenmemiş", "mdi6.alert-circle-outline", palette.danger)
        for card in (
            self.kpi_entries,
            self.kpi_revenue,
            self.kpi_stay,
            self.kpi_unique,
            self.kpi_unpaid,
        ):
            kpis.addWidget(card)
        root.addLayout(kpis)

        grid = QGridLayout()
        grid.setSpacing(14)
        self.revenue_chart = ColumnChart(value_format=compact)
        self.traffic_chart = ColumnChart()
        self.hourly_chart = ColumnChart()
        self.type_chart = BarListChart()
        self.method_chart = BarListChart(empty_text="Bu dönemde ödeme yok")
        for chart in (self.revenue_chart, self.traffic_chart, self.hourly_chart):
            chart.setMinimumHeight(230)
        grid.addWidget(_chart_card("Günlük tahsilat", self.currency, self.revenue_chart), 0, 0)
        grid.addWidget(_chart_card("Araç tipleri", "giriş sayısı", self.type_chart), 0, 1)
        grid.addWidget(_chart_card("Günlük giriş / çıkış", "", self.traffic_chart), 1, 0)
        grid.addWidget(_chart_card("Ödeme yöntemleri", self.currency, self.method_chart), 1, 1)
        grid.addWidget(
            _chart_card("Saatlik yoğunluk", "günlük ortalama giriş", self.hourly_chart), 2, 0, 1, 2
        )
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 1)
        root.addLayout(grid)
        root.addStretch(1)

        self._debounce = QTimer(self, singleShot=True, interval=200)
        self._debounce.timeout.connect(self.reload)
        self.start.dateChanged.connect(lambda *_: self._debounce.start())
        self.end.dateChanged.connect(lambda *_: self._debounce.start())
        controller.data_changed.connect(self._debounce.start)
        self.summary = None
        self.reload()

    def _quick(self, days: int) -> None:
        today = date.today()
        self.start.setDate(_qdate(today - timedelta(days=days)))
        self.end.setDate(_qdate(today))

    def _this_month(self) -> None:
        today = date.today()
        self.start.setDate(_qdate(today.replace(day=1)))
        self.end.setDate(_qdate(today))

    def period(self) -> tuple[date, date]:
        start, end = self.start.date().toPython(), self.end.date().toPython()
        return (start, end) if start <= end else (end, start)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._debounce.start()

    def reload(self) -> None:
        start, end = self.period()
        report = self.ctx.reports.summary(start, end)
        self.summary = report
        currency = self.currency
        days = report.day_count

        self.kpi_entries.set_value(
            f"{report.entries:,}".replace(",", "."), f"günde ort. {report.entries / days:.0f}"
        )
        self.kpi_revenue.set_value(
            format_money(report.revenue, currency),
            f"günlük ort. {format_money(report.average_daily_revenue, currency)}",
        )
        self.kpi_stay.set_value(format_duration(report.average_stay), f"{report.exits} çıkış")
        peak = report.peak_hour
        self.kpi_unique.set_value(
            f"{report.unique_plates:,}".replace(",", "."),
            f"en yoğun saat {peak:02d}:00" if peak is not None else "",
        )
        self.kpi_unpaid.set_value(
            format_money(report.unpaid_amount, currency), f"{report.unpaid_count} kayıt"
        )

        labels = [d.day.strftime("%d.%m") for d in report.days]
        weekdays = ("Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz")
        tips = [f"{d.day:%d.%m.%Y} {weekdays[d.day.weekday()]}" for d in report.days]
        self.revenue_chart.value_format = lambda v: compact(v)
        self.revenue_chart.set_data(
            labels,
            [Series("Tahsilat", series_color(0), [float(d.revenue) for d in report.days])],
            tips,
        )
        self.traffic_chart.set_data(
            labels,
            [
                Series("Giriş", entry_color(), [d.entries for d in report.days]),
                Series("Çıkış", exit_color(), [d.exits for d in report.days]),
            ],
            tips,
        )
        self.hourly_chart.set_data(
            [f"{h:02d}" for h in range(24)],
            [
                Series(
                    "Ortalama giriş",
                    series_color(0),
                    [round(v / days, 1) for v in report.hourly_entries],
                )
            ],
            [f"{h:02d}:00 – {(h + 1) % 24:02d}:00" for h in range(24)],
        )
        total = sum(report.by_type.values()) or 1
        self.type_chart.set_items(
            [
                BarItem(
                    vtype.label,
                    count,
                    vehicle_color(vtype),
                    f"{count} · %{count / total * 100:.0f}",
                )
                for vtype, count in report.by_type.items()
            ]
        )
        self.method_chart.set_items(
            [
                BarItem(
                    method.label, float(amount), series_color(0), format_money(amount, currency)
                )
                for method, amount in report.revenue_by_method.items()
                if amount > 0
            ]
        )

    def export(self, kind: str) -> None:
        start, end = self.period()
        default = f"otopark_{start:%Y%m%d}-{end:%Y%m%d}.{kind}"
        pattern = "Excel (*.xlsx)" if kind == "xlsx" else "CSV (*.csv)"
        path, _ = QFileDialog.getSaveFileName(
            self, "Dışa aktar", str(Path.home() / default), pattern
        )
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != f".{kind}":
            target = target.with_suffix(f".{kind}")
        try:
            sessions = sessions_for_export(self.ctx.db, start, end)
            if kind == "xlsx":
                summary = self.ctx.reports.summary(start, end)
                export_sessions_xlsx(sessions, target, summary=summary, currency=self.currency)
            else:
                export_sessions_csv(sessions, target)
        except OSError as exc:
            show_error(self, f"Dosya yazılamadı:\n{exc}")
            return
        self.controller.toast("Dışa aktarıldı", f"{len(sessions)} kayıt → {target}", "success")
