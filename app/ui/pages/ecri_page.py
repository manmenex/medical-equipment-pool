"""ECRI Alerts Tracker page (FUNCTION 2)."""

from __future__ import annotations

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
from app.services.ecri_service import ECRI_SERVICE_NAME
from app.ui.pages.login_dialog import LoginDialog
from app.ui.widgets.table_utils import populate_table
from app.ui.widgets.worker import Worker


class ECRIPage(QWidget):
    def __init__(self, context: AppContext, parent=None):
        super().__init__(parent)
        self.context = context
        self._worker: Worker | None = None

        outer = QVBoxLayout(self)
        title = QLabel("ECRI Alerts Tracker")
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

        self.login_status_label = QLabel()
        form_row.addWidget(self.login_status_label)

        self.login_button = QPushButton("Configure Login")
        self.login_button.clicked.connect(self._on_login_clicked)
        form_row.addWidget(self.login_button)

        self.fetch_button = QPushButton("Search ECRI Alerts")
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

        self._update_login_status()
        self.refresh_table()

    def _update_login_status(self) -> None:
        configured = self.context.ecri_service.has_credentials()
        self.login_status_label.setText(
            "Credentials: Configured" if configured else "Credentials: Not configured"
        )

    def _on_login_clicked(self) -> None:
        dialog = LoginDialog(ECRI_SERVICE_NAME, self.context.credential_service, self)
        if dialog.exec():
            self._update_login_status()

    def _on_fetch_clicked(self) -> None:
        if not self.context.ecri_service.has_credentials():
            QMessageBox.information(
                self, "Login required", "Please configure your ECRI credentials first."
            )
            self._on_login_clicked()
            if not self.context.ecri_service.has_credentials():
                return

        start = self.start_date_edit.date().toPython()
        end = self.end_date_edit.date().toPython()
        if start > end:
            QMessageBox.warning(self, "Invalid range", "Start Date must be before End Date.")
            return

        self.fetch_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setText(f"Logging in and searching ECRI alerts from {start} to {end} ...")

        self._worker = Worker(self.context.ecri_service.refresh, start, end)
        self._worker.finished.connect(self._on_fetch_finished)
        self._worker.failed.connect(self._on_fetch_failed)
        self._worker.start()

    def _on_fetch_finished(self, result) -> None:
        new_count, updated_count = result
        self.progress_bar.setVisible(False)
        self.fetch_button.setEnabled(True)
        self.status_label.setText(f"Done: {new_count} new, {updated_count} updated alerts.")
        self.refresh_table()

    def _on_fetch_failed(self, message: str) -> None:
        self.progress_bar.setVisible(False)
        self.fetch_button.setEnabled(True)
        self.status_label.setText("Search failed - see message below.")
        QMessageBox.critical(self, "ECRI search failed", message)

    def refresh_table(self) -> None:
        alerts = self.context.ecri_service.list_all()
        populate_table(
            self.table,
            alerts,
            [
                ("Alert Number", lambda a: a.alert_number),
                ("Title", lambda a: a.title),
                ("Manufacturer", lambda a: a.manufacturer),
                ("Product", lambda a: a.product),
                ("Model #", lambda a: a.model_number),
                ("Hazard Level", lambda a: a.hazard_level),
                ("Date Issued", lambda a: a.date_issued),
                ("Status", lambda a: a.status),
            ],
        )
