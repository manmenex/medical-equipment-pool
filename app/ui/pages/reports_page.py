"""Weekly report generation page (FUNCTIONS 5 & 6)."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.app_context import AppContext
from app.services.period_service import get_period
from app.services.report_service import ReportFilters
from app.ui.widgets.worker import Worker


class ReportsPage(QWidget):
    def __init__(self, context: AppContext, parent=None):
        super().__init__(parent)
        self.context = context
        self._worker: Worker | None = None

        outer = QVBoxLayout(self)
        title = QLabel("Weekly Recall Reports")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        outer.addWidget(title)

        form_row = QHBoxLayout()
        form = QFormLayout()

        self.year_spin = QSpinBox()
        self.year_spin.setRange(2000, 2100)
        self.year_spin.setValue(date.today().year)
        form.addRow("Year:", self.year_spin)

        self.month_combo = QComboBox()
        self.month_combo.addItems([date(2000, m, 1).strftime("%B") for m in range(1, 13)])
        self.month_combo.setCurrentIndex(date.today().month - 1)
        form.addRow("Month:", self.month_combo)

        self.week_combo = QComboBox()
        self.week_combo.addItems(["Week 1 (1-7)", "Week 2 (8-14)", "Week 3 (15-21)", "Week 4 (22-End)"])
        form.addRow("Week:", self.week_combo)

        form_row.addLayout(form)

        filter_form = QFormLayout()
        self.manufacturer_filter = QLineEdit()
        self.department_filter = QLineEdit()
        self.recall_class_filter = QComboBox()
        self.recall_class_filter.addItems(["All", "Class I", "Class II", "Class III"])
        filter_form.addRow("Filter Manufacturer:", self.manufacturer_filter)
        filter_form.addRow("Filter Department:", self.department_filter)
        filter_form.addRow("Filter Recall Class:", self.recall_class_filter)
        form_row.addLayout(filter_form)

        self.generate_button = QPushButton("Generate Report")
        self.generate_button.clicked.connect(self._on_generate_clicked)
        form_row.addWidget(self.generate_button)
        form_row.addStretch(1)
        outer.addLayout(form_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        outer.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        outer.addWidget(QLabel("Previously Generated Reports:"))
        self.history_table = QTableWidget()
        outer.addWidget(self.history_table, stretch=1)

        self.refresh_history()

    def _on_generate_clicked(self) -> None:
        year = self.year_spin.value()
        month = self.month_combo.currentIndex() + 1
        week_number = self.week_combo.currentIndex() + 1
        period = get_period(year, month, week_number)

        recall_class = self.recall_class_filter.currentText()
        filters = ReportFilters(
            manufacturer=self.manufacturer_filter.text().strip() or None,
            department=self.department_filter.text().strip() or None,
            recall_class=None if recall_class == "All" else recall_class,
        )

        self.generate_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setText(f"Generating report for {period.label} ...")

        self._worker = Worker(
            self.context.report_service.generate_weekly_report,
            year,
            month,
            week_number,
            ("excel", "pdf"),
            filters,
        )
        self._worker.finished.connect(self._on_generate_finished)
        self._worker.failed.connect(self._on_generate_failed)
        self._worker.start()

    def _on_generate_finished(self, outputs: dict) -> None:
        self.progress_bar.setVisible(False)
        self.generate_button.setEnabled(True)
        paths = ", ".join(str(p) for p in outputs.values())
        self.status_label.setText(f"Report generated: {paths}")
        self.refresh_history()

    def _on_generate_failed(self, message: str) -> None:
        self.progress_bar.setVisible(False)
        self.generate_button.setEnabled(True)
        self.status_label.setText("Report generation failed - see message below.")
        QMessageBox.critical(self, "Report generation failed", message)

    def refresh_history(self) -> None:
        runs = self.context.report_service.list_report_runs()
        headers = [
            "Period", "Start", "End", "FDA", "ECRI", "Matched", "Possible", "Not Matched",
            "Excel", "PDF",
        ]
        self.history_table.clear()
        self.history_table.setColumnCount(len(headers))
        self.history_table.setHorizontalHeaderLabels(headers)
        self.history_table.setRowCount(len(runs))
        for row_index, run in enumerate(runs):
            values = [
                run["period_label"], run["start_date"], run["end_date"], run["total_fda"],
                run["total_ecri"], run["total_matched"], run["total_possible"], run["total_not_matched"],
            ]
            for col_index, value in enumerate(values):
                self.history_table.setItem(row_index, col_index, QTableWidgetItem(str(value)))

            for col_index, path_key in ((8, "excel_path"), (9, "pdf_path")):
                path = run[path_key]
                if path:
                    button = QPushButton("Open")
                    button.clicked.connect(lambda _checked, p=path: QDesktopServices.openUrl(QUrl.fromLocalFile(p)))
                    self.history_table.setCellWidget(row_index, col_index, button)
        self.history_table.resizeColumnsToContents()
