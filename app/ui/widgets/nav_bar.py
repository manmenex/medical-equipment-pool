"""Left-hand navigation rail used by the main window."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QLabel, QPushButton, QVBoxLayout

NAV_ITEMS: list[tuple[str, str]] = [
    ("dashboard", "Dashboard"),
    ("fda", "FDA Recalls"),
    ("ecri", "ECRI Alerts"),
    ("inventory", "Inventory"),
    ("matching", "Matching"),
    ("search", "Search"),
    ("reports", "Reports"),
    ("settings", "Settings"),
]


class NavBar(QFrame):
    page_selected = Signal(str)

    def __init__(self, app_name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("NavPanel")
        self.setFixedWidth(200)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 16, 8, 16)
        layout.setSpacing(4)

        title = QLabel(app_name)
        title.setStyleSheet("font-size: 15px; font-weight: 700; padding: 8px 12px 16px 12px;")
        title.setWordWrap(True)
        layout.addWidget(title)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}

        for key, label in NAV_ITEMS:
            button = QPushButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked, k=key: self.page_selected.emit(k))
            layout.addWidget(button)
            self._group.addButton(button)
            self._buttons[key] = button

        layout.addStretch(1)
        self._buttons["dashboard"].setChecked(True)

    def select(self, key: str) -> None:
        if key in self._buttons:
            self._buttons[key].setChecked(True)
