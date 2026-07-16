"""Settings page (FUNCTION 9)."""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.services.app_context import AppContext
from app.services.backup_service import BackupService
from app.services.ecri_service import ECRI_SERVICE_NAME
from app.ui.pages.login_dialog import LoginDialog


class SettingsPage(QWidget):
    def __init__(
        self,
        context: AppContext,
        scheduler_manager=None,
        on_theme_changed: Optional[Callable[[str], None]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.context = context
        self.scheduler_manager = scheduler_manager
        self.on_theme_changed = on_theme_changed
        self.backup_service = BackupService(context.settings.database_path, context.settings.backup_dir)

        outer = QVBoxLayout(self)
        title = QLabel("Settings")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        outer.addWidget(title)

        outer.addWidget(self._build_matching_group())
        outer.addWidget(self._build_general_group())
        outer.addWidget(self._build_scheduler_group())
        outer.addWidget(self._build_credentials_group())
        outer.addWidget(self._build_backup_group())
        outer.addStretch(1)

        self.status_label = QLabel("")
        outer.addWidget(self.status_label)

    # -- Matching thresholds ---------------------------------------------------
    def _build_matching_group(self) -> QGroupBox:
        box = QGroupBox("Matching Engine")
        form = QFormLayout(box)

        self.matched_threshold_spin = QDoubleSpinBox()
        self.matched_threshold_spin.setRange(0, 100)
        self.matched_threshold_spin.setValue(self.context.matching_service.matched_threshold)
        self.matched_threshold_spin.setSuffix("%")
        self.matched_threshold_spin.valueChanged.connect(self._save_thresholds)
        form.addRow("Similarity Threshold (Matched):", self.matched_threshold_spin)

        self.possible_threshold_spin = QDoubleSpinBox()
        self.possible_threshold_spin.setRange(0, 100)
        self.possible_threshold_spin.setValue(self.context.matching_service.possible_threshold)
        self.possible_threshold_spin.setSuffix("%")
        self.possible_threshold_spin.valueChanged.connect(self._save_thresholds)
        form.addRow("Possible Match Threshold:", self.possible_threshold_spin)

        return box

    def _save_thresholds(self) -> None:
        self.context.matching_service.matched_threshold = self.matched_threshold_spin.value()
        self.context.matching_service.possible_threshold = self.possible_threshold_spin.value()
        self._persist_setting("fuzzy_match_threshold", str(self.matched_threshold_spin.value()))
        self._persist_setting("possible_match_threshold", str(self.possible_threshold_spin.value()))

    # -- General (download folder, auto update/login, theme) -------------------
    def _build_general_group(self) -> QGroupBox:
        box = QGroupBox("General")
        form = QFormLayout(box)

        folder_row = QHBoxLayout()
        self.download_folder_edit = QLineEdit(str(self.context.settings.download_dir))
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self._on_browse_download_folder)
        folder_row.addWidget(self.download_folder_edit)
        folder_row.addWidget(browse_button)
        form.addRow("Download Folder:", folder_row)

        self.auto_update_check = QCheckBox("Automatically check for recalls on schedule")
        self.auto_update_check.setChecked(self.context.settings.scheduler_enabled)
        self.auto_update_check.toggled.connect(
            lambda checked: self._persist_setting("scheduler_enabled", str(checked))
        )
        form.addRow(self.auto_update_check)

        self.auto_login_check = QCheckBox("Automatically re-login to ECRI if the session expires")
        self.auto_login_check.setChecked(True)
        self.auto_login_check.toggled.connect(
            lambda checked: self._persist_setting("auto_login", str(checked))
        )
        form.addRow(self.auto_login_check)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark", "Light"])
        self.theme_combo.setCurrentText(self.context.settings.ui_theme.capitalize())
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        form.addRow("Theme:", self.theme_combo)

        return box

    def _on_browse_download_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Download Folder", self.download_folder_edit.text())
        if folder:
            self.download_folder_edit.setText(folder)
            self.context.report_service.output_dir = folder
            self._persist_setting("download_dir", folder)

    def _on_theme_changed(self, theme_text: str) -> None:
        theme = theme_text.lower()
        self._persist_setting("ui_theme", theme)
        if self.on_theme_changed:
            self.on_theme_changed(theme)

    # -- Scheduler ---------------------------------------------------------------
    def _build_scheduler_group(self) -> QGroupBox:
        box = QGroupBox("Automatic Scheduler")
        form = QFormLayout(box)

        self.frequency_combo = QComboBox()
        self.frequency_combo.addItems(["daily", "weekly", "monthly"])
        self.frequency_combo.setCurrentText(self.context.settings.scheduler_frequency)
        form.addRow("Frequency:", self.frequency_combo)

        self.hour_spin = QSpinBox()
        self.hour_spin.setRange(0, 23)
        self.hour_spin.setValue(self.context.settings.scheduler_hour)
        form.addRow("Hour (24h):", self.hour_spin)

        self.minute_spin = QSpinBox()
        self.minute_spin.setRange(0, 59)
        self.minute_spin.setValue(self.context.settings.scheduler_minute)
        form.addRow("Minute:", self.minute_spin)

        save_button = QPushButton("Save Schedule")
        save_button.clicked.connect(self._on_save_schedule)
        form.addRow(save_button)

        run_now_button = QPushButton("Run Check Now")
        run_now_button.clicked.connect(self._on_run_now)
        form.addRow(run_now_button)

        return box

    def _on_save_schedule(self) -> None:
        if self.scheduler_manager is None:
            QMessageBox.warning(self, "Scheduler unavailable", "The scheduler is not running in this session.")
            return
        self.scheduler_manager.configure(
            self.frequency_combo.currentText(), self.hour_spin.value(), self.minute_spin.value()
        )
        self.scheduler_manager.start()
        self.status_label.setText("Schedule saved and scheduler is running.")

    def _on_run_now(self) -> None:
        if self.scheduler_manager is None:
            QMessageBox.warning(self, "Scheduler unavailable", "The scheduler is not running in this session.")
            return
        self.status_label.setText("Running check now - this may take a while ...")
        self.scheduler_manager.run_now()
        self.status_label.setText("Manual check finished. See Dashboard for the latest results.")

    # -- Credentials ---------------------------------------------------------------
    def _build_credentials_group(self) -> QGroupBox:
        box = QGroupBox("ECRI Credentials")
        layout = QHBoxLayout(box)
        self.credential_status_label = QLabel()
        self._refresh_credential_status()
        layout.addWidget(self.credential_status_label)

        change_button = QPushButton("Change Credentials")
        change_button.clicked.connect(self._on_change_credentials)
        layout.addWidget(change_button)

        remove_button = QPushButton("Remove Credentials")
        remove_button.clicked.connect(self._on_remove_credentials)
        layout.addWidget(remove_button)
        layout.addStretch(1)
        return box

    def _refresh_credential_status(self) -> None:
        info = self.context.credential_service.get_info(ECRI_SERVICE_NAME)
        self.credential_status_label.setText(
            f"Configured for user: {info.username}" if info.is_configured else "Not configured"
        )

    def _on_change_credentials(self) -> None:
        dialog = LoginDialog(ECRI_SERVICE_NAME, self.context.credential_service, self)
        if dialog.exec():
            self._refresh_credential_status()

    def _on_remove_credentials(self) -> None:
        reply = QMessageBox.question(self, "Remove credentials", "Remove the stored ECRI credentials?")
        if reply == QMessageBox.StandardButton.Yes:
            self.context.credential_service.delete_credentials(ECRI_SERVICE_NAME)
            self._refresh_credential_status()

    # -- Backup ---------------------------------------------------------------------
    def _build_backup_group(self) -> QGroupBox:
        box = QGroupBox("Database Backup")
        layout = QHBoxLayout(box)
        backup_button = QPushButton("Backup Database Now")
        backup_button.clicked.connect(self._on_backup_clicked)
        layout.addWidget(backup_button)
        layout.addStretch(1)
        return box

    def _on_backup_clicked(self) -> None:
        try:
            path = self.backup_service.create_backup()
            QMessageBox.information(self, "Backup complete", f"Database backed up to:\n{path}")
        except OSError as exc:
            QMessageBox.critical(self, "Backup failed", str(exc))

    # -- persistence helper -----------------------------------------------------------
    def _persist_setting(self, key: str, value: str) -> None:
        self.context.db.execute(
            "INSERT OR REPLACE INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, datetime.now().isoformat()),
        )
