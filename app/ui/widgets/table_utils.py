"""Helpers for filling a QTableWidget from a list of objects."""

from __future__ import annotations

from typing import Any, Callable, Sequence

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem


ColumnSpec = tuple[str, Callable[[Any], Any]]


def populate_table(
    table: QTableWidget,
    rows: Sequence[Any],
    columns: Sequence[ColumnSpec],
    row_color: Callable[[Any], str | None] | None = None,
) -> None:
    """Fill `table` with one row per item in `rows`.

    `columns` is a list of (header_text, getter) pairs; `row_color`, if
    given, returns an optional hex color string used to tint the row
    (e.g. green/amber/red for match status).
    """
    table.clear()
    table.setColumnCount(len(columns))
    table.setHorizontalHeaderLabels([c[0] for c in columns])
    table.setRowCount(len(rows))
    table.setSortingEnabled(False)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

    for row_index, item in enumerate(rows):
        color = row_color(item) if row_color else None
        for col_index, (_, getter) in enumerate(columns):
            value = getter(item)
            cell = QTableWidgetItem("" if value is None else str(value))
            if color:
                cell.setBackground(QColor(color))
            table.setItem(row_index, col_index, cell)

    table.setSortingEnabled(True)
    table.resizeColumnsToContents()
