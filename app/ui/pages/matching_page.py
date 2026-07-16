"""Matching engine page (FUNCTION 4)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
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

from app.models.enums import MatchStatus
from app.services.app_context import AppContext
from app.ui.theme import STATUS_COLORS
from app.ui.widgets.table_utils import populate_table
from app.ui.widgets.worker import Worker


class MatchingPage(QWidget):
    def __init__(self, context: AppContext, parent=None):
        super().__init__(parent)
        self.context = context
        self._worker: Worker | None = None
        self._all_results: list = []

        outer = QVBoxLayout(self)
        title = QLabel("Recall Matching Engine")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        outer.addWidget(title)

        form_row = QHBoxLayout()
        form = QFormLayout()
        self.matched_threshold_spin = QDoubleSpinBox()
        self.matched_threshold_spin.setRange(0, 100)
        self.matched_threshold_spin.setValue(context.matching_service.matched_threshold)
        self.matched_threshold_spin.setSuffix("%")
        form.addRow("Matched Threshold:", self.matched_threshold_spin)

        self.possible_threshold_spin = QDoubleSpinBox()
        self.possible_threshold_spin.setRange(0, 100)
        self.possible_threshold_spin.setValue(context.matching_service.possible_threshold)
        self.possible_threshold_spin.setSuffix("%")
        form.addRow("Possible Match Threshold:", self.possible_threshold_spin)
        form_row.addLayout(form)

        self.run_button = QPushButton("Run Matching")
        self.run_button.clicked.connect(self._on_run_clicked)
        form_row.addWidget(self.run_button)

        self.status_filter = QComboBox()
        self.status_filter.addItems(["All", "Matched", "Possible Match", "Not Matched"])
        self.status_filter.currentTextChanged.connect(self._apply_filter)
        form_row.addWidget(QLabel("Filter:"))
        form_row.addWidget(self.status_filter)
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

    def _on_run_clicked(self) -> None:
        self.context.matching_service.matched_threshold = self.matched_threshold_spin.value()
        self.context.matching_service.possible_threshold = self.possible_threshold_spin.value()

        self.run_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setText("Running matching engine against the full inventory ...")

        def _run():
            fda = self.context.fda_service.list_all()
            ecri = self.context.ecri_service.list_all()
            inventory = self.context.inventory_service.list_all()
            results = self.context.matching_service.match_all(fda, ecri, inventory)
            self.context.match_repository.save_all(results)
            return results

        self._worker = Worker(_run)
        self._worker.finished.connect(self._on_run_finished)
        self._worker.failed.connect(self._on_run_failed)
        self._worker.start()

    def _on_run_finished(self, results: list) -> None:
        self.progress_bar.setVisible(False)
        self.run_button.setEnabled(True)
        matched = sum(1 for r in results if r.status == MatchStatus.MATCHED)
        possible = sum(1 for r in results if r.status == MatchStatus.POSSIBLE_MATCH)
        not_matched = sum(1 for r in results if r.status == MatchStatus.NOT_MATCHED)
        self.status_label.setText(
            f"Matching complete: {matched} matched, {possible} possible, {not_matched} not matched."
        )
        self.refresh_table()

    def _on_run_failed(self, message: str) -> None:
        self.progress_bar.setVisible(False)
        self.run_button.setEnabled(True)
        self.status_label.setText("Matching failed - see message below.")
        QMessageBox.critical(self, "Matching failed", message)

    def refresh_table(self) -> None:
        self._all_results = self.context.match_repository.list_all()
        self._apply_filter(self.status_filter.currentText())

    def _apply_filter(self, status_text: str) -> None:
        rows = self._all_results
        if status_text != "All":
            rows = [r for r in rows if r.status.value == status_text]

        populate_table(
            self.table,
            rows,
            [
                ("Recall Source", lambda m: m.recall_source.value),
                ("Recall Number", lambda m: m.recall_number),
                ("Hospital Asset #", lambda m: m.hospital_asset_number),
                ("Manufacturer", lambda m: m.manufacturer),
                ("Model", lambda m: m.model),
                ("Confidence", lambda m: f"{m.confidence_score:.0f}%"),
                ("Status", lambda m: m.status.value),
                ("Method", lambda m: m.method.value),
                ("Reason", lambda m: m.reason),
            ],
            row_color=lambda m: STATUS_COLORS.get(m.status.value),
        )
