"""Sütun tanımlarıyla çalışan genel tablo modeli."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView

from plakatanima.gui.widgets.plate import PlateDelegate

SORT_ROLE = Qt.ItemDataRole.UserRole
ALERT_ROLE = Qt.ItemDataRole.UserRole + 1
LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
CENTER = Qt.AlignmentFlag.AlignCenter


@dataclass(slots=True)
class Column:
    title: str
    text: Callable[[Any], str]
    sort: Callable[[Any], Any] | None = None
    align: Qt.AlignmentFlag = LEFT
    icon: Callable[[Any], QIcon | None] | None = None
    color: Callable[[Any], str | None] | None = None
    tooltip: Callable[[Any], str] | None = None
    width: int | None = None


class RowModel(QAbstractTableModel):
    def __init__(
        self,
        columns: Sequence[Column],
        *,
        alert: Callable[[Any], bool] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.columns = list(columns)
        self._rows: list[Any] = []
        self._alert = alert

    def set_rows(self, rows: Sequence[Any]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def refresh(self) -> None:
        """Satırlar aynı, hesaplanan değerler (süre, ücret) değişti."""
        if self._rows:
            top = self.index(0, 0)
            bottom = self.index(len(self._rows) - 1, len(self.columns) - 1)
            self.dataChanged.emit(top, bottom)

    def rows(self) -> list[Any]:
        return list(self._rows)

    def row_at(self, row: int) -> Any:
        return self._rows[row]

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                return self.columns[section].title
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return self.columns[section].align
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        column = self.columns[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            return column.text(row)
        if role == SORT_ROLE:
            return column.sort(row) if column.sort else column.text(row)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return column.align
        if role == Qt.ItemDataRole.DecorationRole and column.icon:
            return column.icon(row)
        if role == Qt.ItemDataRole.ForegroundRole and column.color:
            color = column.color(row)
            return QColor(color) if color else None
        if role == Qt.ItemDataRole.ToolTipRole and column.tooltip:
            return column.tooltip(row)
        if role == ALERT_ROLE and self._alert:
            return self._alert(row)
        return None


class _SortProxy(QSortFilterProxyModel):
    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        a, b = left.data(SORT_ROLE), right.data(SORT_ROLE)
        if a is None:
            return b is not None
        if b is None:
            return False
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


class DataTable(QTableView):
    def __init__(self, model: RowModel, *, plate_column: int | None = 0, parent=None):
        super().__init__(parent)
        self.row_model = model
        self.proxy = _SortProxy(self)
        self.proxy.setSourceModel(model)
        self.proxy.setSortRole(SORT_ROLE)
        self.setModel(self.proxy)
        self.setSortingEnabled(True)
        # Başlangıçta servisin verdiği sıra (ör. en yeni kayıt üstte) korunsun.
        self.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(40)
        header = self.horizontalHeader()
        header.setHighlightSections(False)
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        if plate_column is not None:
            self.setItemDelegateForColumn(plate_column, PlateDelegate(self))
            self.setColumnWidth(plate_column, 140)
        for i, column in enumerate(model.columns):
            if column.width:
                self.setColumnWidth(i, column.width)

    def selected_row(self) -> Any | None:
        indexes = self.selectionModel().selectedRows()
        if not indexes:
            return None
        return self.row_model.row_at(self.proxy.mapToSource(indexes[0]).row())

    def row_for_index(self, index: QModelIndex) -> Any:
        return self.row_model.row_at(self.proxy.mapToSource(index).row())
