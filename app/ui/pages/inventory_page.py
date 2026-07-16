"""Hospital Inventory page (FUNCTION 3)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.app_context import AppContext
from app.ui.widgets.table_utils import populate_table
from app.ui.widgets.worker import Worker


class InventoryPage(QWidget):
    def __init__(self, context: AppContext, parent=None):
        super().__init__(parent)
        self.context = context
        self._worker: Worker | None = None

        outer = QVBoxLayout(self)
        title = QLabel("Hospital Medical Device Inventory")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        outer.addWidget(title)

        button_row = QHBoxLayout()
        self.import_button = QPushButton("Import Excel Inventory (.xlsx / .xls)")
        self.import_button.clicked.connect(self._on_import_clicked)
        button_row.addWidget(self.import_button)
        button_row.addStretch(1)
        outer.addLayout(button_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        outer.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        self.table = QTableWidget()
        outer.addWidget(self.table, stretch=1)

        self.refresh_table()

    def _on_import_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Hospital Inventory Excel File", "", "Excel Files (*.xlsx *.xls)"
        )
        if not path:
            return

        self.import_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setText(f"Importing {path} ...")

        self._worker = Worker(self.context.inventory_service.import_excel, path)
        self._worker.finished.connect(self._on_import_finished)
        self._worker.failed.connect(self._on_import_failed)
        self._worker.start()

    def _on_import_finished(self, result) -> None:
        self.progress_bar.setVisible(False)
        self.import_button.setEnabled(True)
        message = (
            f"Imported {result.imported} new, updated {result.updated}, "
            f"skipped {result.skipped} (of {result.total_rows} rows)."
        )
        if result.warnings:
            message += " " + " ".join(result.warnings)
        self.status_label.setText(message)
        self.refresh_table()

    def _on_import_failed(self, message: str) -> None:
        self.progress_bar.setVisible(False)
        self.import_button.setEnabled(True)
        self.status_label.setText("Import failed - see message below.")
        QMessageBox.critical(self, "Inventory import failed", message)

    def refresh_table(self) -> None:
        items = self.context.inventory_service.list_all()
        populate_table(
            self.table,
            items,
            [
                ("Asset Number", lambda i: i.asset_number),
                ("Equipment Code", lambda i: i.equipment_code),
                ("Device Name", lambda i: i.device_name),
                ("Manufacturer", lambda i: i.manufacturer),
                ("Brand", lambda i: i.brand),
                ("Model #", lambda i: i.model_number),
                ("Catalog #", lambda i: i.catalog_number),
                ("Serial #", lambda i: i.serial_number),
                ("Department", lambda i: i.department),
                ("Location", lambda i: i.location),
                ("Purchase Date", lambda i: i.purchase_date),
                ("Status", lambda i: i.status),
            ],
        )
