"""
Credential prompt dialog (FUNCTION 2 - ECRI SCRAPER).

Shown the first time the app needs to reach ECRI (or whenever the user
chooses "Change ECRI Credentials" in Settings). Credentials are handed to
`CredentialService` immediately on accept and never held anywhere else.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from app.services.credential_service import CredentialService


class LoginDialog(QDialog):
    """Simple modal dialog asking for a portal's username/password."""

    def __init__(self, service_name: str, credential_service: CredentialService, parent=None):
        super().__init__(parent)
        self._service_name = service_name
        self._credential_service = credential_service

        self.setWindowTitle(f"{service_name} Login")
        self.setModal(True)
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        info = QLabel(
            f"Enter your {service_name} portal credentials.\n"
            "They are encrypted and stored in your OS credential vault - "
            "never in plain text or in this application's source/config."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self.username_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Username / Email:", self.username_edit)
        form.addRow("Password:", self.password_edit)
        layout.addLayout(form)

        existing = credential_service.get_credentials(service_name)
        if existing:
            self.username_edit.setText(existing[0])

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        if not username or not password:
            QMessageBox.warning(self, "Missing information", "Username and password are both required.")
            return
        self._credential_service.save_credentials(self._service_name, username, password)
        self.accept()

    @staticmethod
    def prompt_if_needed(service_name: str, credential_service: CredentialService, parent=None) -> bool:
        """Show the dialog only if credentials aren't already stored.

        Returns True if credentials are available after the call (either
        already stored, or the user just supplied them).
        """
        if credential_service.has_credentials(service_name):
            return True
        dialog = LoginDialog(service_name, credential_service, parent)
        return dialog.exec() == QDialog.DialogCode.Accepted
