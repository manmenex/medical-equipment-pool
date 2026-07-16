"""Advanced search page (FUNCTION 8).

Searches across FDA recalls, ECRI alerts and hospital inventory using
parametrized SQL `LIKE` queries (no string-built SQL, so user-entered
search text can never be used for SQL injection).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.app_context import AppContext
from app.ui.widgets.table_utils import populate_table


class SearchPage(QWidget):
    def __init__(self, context: AppContext, parent=None):
        super().__init__(parent)
        self.context = context

        outer = QVBoxLayout(self)
        title = QLabel("Advanced Search")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        outer.addWidget(title)

        form_row = QHBoxLayout()
        form = QFormLayout()
        self.manufacturer_edit = QLineEdit()
        self.model_edit = QLineEdit()
        self.asset_number_edit = QLineEdit()
        self.recall_number_edit = QLineEdit()
        self.product_edit = QLineEdit()
        self.department_edit = QLineEdit()
        self.status_edit = QLineEdit()

        form.addRow("Manufacturer:", self.manufacturer_edit)
        form.addRow("Model:", self.model_edit)
        form.addRow("Asset Number:", self.asset_number_edit)
        form.addRow("Recall Number:", self.recall_number_edit)
        form.addRow("Product:", self.product_edit)
        form.addRow("Department:", self.department_edit)
        form.addRow("Status:", self.status_edit)
        form_row.addLayout(form)

        search_button = QPushButton("Search")
        search_button.clicked.connect(self._on_search_clicked)
        form_row.addWidget(search_button)
        form_row.addStretch(1)
        outer.addLayout(form_row)

        self.result_label = QLabel("")
        outer.addWidget(self.result_label)

        self.table = QTableWidget()
        outer.addWidget(self.table, stretch=1)

    def _like(self, value: str) -> str:
        return f"%{value.strip()}%"

    def _on_search_clicked(self) -> None:
        db = self.context.db
        results: list[tuple[str, ...]] = []

        manufacturer = self.manufacturer_edit.text().strip()
        model = self.model_edit.text().strip()
        asset_number = self.asset_number_edit.text().strip()
        recall_number = self.recall_number_edit.text().strip()
        product = self.product_edit.text().strip()
        department = self.department_edit.text().strip()
        status = self.status_edit.text().strip()

        if recall_number or product or (manufacturer and not asset_number and not department):
            clauses, params = [], []
            if manufacturer:
                clauses.append("manufacturer LIKE ?")
                params.append(self._like(manufacturer))
            if model:
                clauses.append("model_number LIKE ?")
                params.append(self._like(model))
            if recall_number:
                clauses.append("recall_number LIKE ?")
                params.append(self._like(recall_number))
            if product:
                clauses.append("product LIKE ?")
                params.append(self._like(product))
            if status:
                clauses.append("status LIKE ?")
                params.append(self._like(status))
            where = " AND ".join(clauses) if clauses else "1=1"
            rows = db.query_all(f"SELECT * FROM fda_recalls WHERE {where} ORDER BY date_initiated DESC", params)
            results += [("FDA Recall", r["recall_number"], r["product"], r["manufacturer"], r["status"]) for r in rows]

        if asset_number or department or (manufacturer and not recall_number):
            clauses, params = [], []
            if manufacturer:
                clauses.append("manufacturer LIKE ?")
                params.append(self._like(manufacturer))
            if model:
                clauses.append("model_number LIKE ?")
                params.append(self._like(model))
            if asset_number:
                clauses.append("asset_number LIKE ?")
                params.append(self._like(asset_number))
            if department:
                clauses.append("department LIKE ?")
                params.append(self._like(department))
            if status:
                clauses.append("status LIKE ?")
                params.append(self._like(status))
            where = " AND ".join(clauses) if clauses else "1=1"
            rows = db.query_all(f"SELECT * FROM inventory_items WHERE {where} ORDER BY asset_number", params)
            results += [
                ("Inventory", r["asset_number"], r["device_name"], r["manufacturer"], r["status"]) for r in rows
            ]

        self.result_label.setText(f"{len(results)} result(s) found.")
        self.table.clear()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Source", "Key", "Name/Product", "Manufacturer", "Status"])
        self.table.setRowCount(len(results))
        from PySide6.QtWidgets import QTableWidgetItem

        for row_index, row in enumerate(results):
            for col_index, value in enumerate(row):
                self.table.setItem(row_index, col_index, QTableWidgetItem(str(value or "")))
        self.table.resizeColumnsToContents()
