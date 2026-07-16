"""FDA Recalls page (FUNCTION 1)."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDateEdit,
    QFormLayout,
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


class FDAPage(QWidget):
    def __init__(self, context: AppContext, parent=None):
        super().__init__(parent)
        self.context = context
        self._worker: Worker | None = None

        outer = QVBoxLayout(self)
        title = QLabel("FDA Medical Device Recalls")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        outer.addWidget(title)

        form_row = QHBoxLayout()
        form = QFormLayout()
        self.start_date_edit = QDateEdit(QDate.currentDate().addDays(-30))
        self.start_date_edit.setCalendarPopup(True)
        self.end_date_edit = QDateEdit(QDate.currentDate())
        self.end_date_edit.setCalendarPopup(True)
        form.addRow("Start Date:", self.start_date_edit)
        form.addRow("End Date:", self.end_date_edit)
        form_row.addLayout(form)

        self.fetch_button = QPushButton("Search FDA Recalls")
        self.fetch_button.clicked.connect(self._on_fetch_clicked)
        form_row.addWidget(self.fetch_button)
        form_row.addStretch(1)
        outer.addLayout(form_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        outer.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        outer.addWidget(self.status_label)

        self.table = QTableWidget()
        outer.addWidget(self.table, stretch=1)

        self.refresh_table()

    def _on_fetch_clicked(self) -> None:
        start = self.start_date_edit.date().toPython()
        end = self.end_date_edit.date().toPython()
        if start > end:
            QMessageBox.warning(self, "Invalid range", "Start Date must be before End Date.")
            return

        self.fetch_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setText(f"Searching FDA recalls from {start} to {end} ...")

        self._worker = Worker(self.context.fda_service.refresh, start, end)
        self._worker.finished.connect(self._on_fetch_finished)
        self._worker.failed.connect(self._on_fetch_failed)
        self._worker.start()

    def _on_fetch_finished(self, result) -> None:
        new_count, updated_count = result
        self.progress_bar.setVisible(False)
        self.fetch_button.setEnabled(True)
        self.status_label.setText(f"Done: {new_count} new, {updated_count} updated recalls.")
        self.refresh_table()

    def _on_fetch_failed(self, message: str) -> None:
        self.progress_bar.setVisible(False)
        self.fetch_button.setEnabled(True)
        self.status_label.setText("Search failed - see message below.")
        QMessageBox.critical(self, "FDA search failed", message)

    def refresh_table(self) -> None:
        recalls = self.context.fda_service.list_all()
        populate_table(
            self.table,
            recalls,
            [
                ("Recall Number", lambda r: r.recall_number),
                ("Class", lambda r: r.recall_class),
                ("Product", lambda r: r.product),
                ("Manufacturer", lambda r: r.manufacturer),
                ("Reason", lambda r: r.reason),
                ("Date Initiated", lambda r: r.date_initiated),
                ("Status", lambda r: r.status),
                ("Distribution", lambda r: r.distribution),
                ("Quantity", lambda r: r.quantity),
                ("Model #", lambda r: r.model_number),
                ("Catalog #", lambda r: r.catalog_number),
            ],
        )
