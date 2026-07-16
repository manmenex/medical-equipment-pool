"""
Main application window: left navigation + stacked pages + status bar
(FUNCTION "USER INTERFACE").
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QStackedWidget, QStatusBar, QWidget

from app.services.app_context import AppContext
from app.services.ecri_service import ECRI_SERVICE_NAME
from app.ui.pages.dashboard_page import DashboardPage
from app.ui.pages.ecri_page import ECRIPage
from app.ui.pages.fda_page import FDAPage
from app.ui.pages.inventory_page import InventoryPage
from app.ui.pages.login_dialog import LoginDialog
from app.ui.pages.matching_page import MatchingPage
from app.ui.pages.reports_page import ReportsPage
from app.ui.pages.search_page import SearchPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.theme import stylesheet_for
from app.ui.widgets.nav_bar import NavBar
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, context: AppContext, scheduler_manager=None):
        super().__init__()
        self.context = context
        self.scheduler_manager = scheduler_manager
        self.theme = context.settings.ui_theme

        self.setWindowTitle(context.settings.app_name)
        self.resize(1400, 900)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(central)

        self.nav_bar = NavBar(context.settings.app_name)
        layout.addWidget(self.nav_bar)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, stretch=1)

        self.pages: dict[str, QWidget] = {}
        self._build_pages()

        self.nav_bar.page_selected.connect(self._on_page_selected)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        self._show_page("dashboard")
        self._maybe_prompt_first_run_ecri_login()

    def _build_pages(self) -> None:
        self.pages["dashboard"] = DashboardPage(self.context)
        self.pages["fda"] = FDAPage(self.context)
        self.pages["ecri"] = ECRIPage(self.context)
        self.pages["inventory"] = InventoryPage(self.context)
        self.pages["matching"] = MatchingPage(self.context)
        self.pages["search"] = SearchPage(self.context)
        self.pages["reports"] = ReportsPage(self.context)
        self.pages["settings"] = SettingsPage(
            self.context, self.scheduler_manager, on_theme_changed=self.apply_theme
        )
        for page in self.pages.values():
            self.stack.addWidget(page)

    def _on_page_selected(self, key: str) -> None:
        self._show_page(key)

    def _show_page(self, key: str) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        self.nav_bar.select(key)
        if hasattr(page, "refresh"):
            page.refresh()
        elif hasattr(page, "refresh_table"):
            page.refresh_table()
        self.status_bar.showMessage(f"{key.capitalize()} - last viewed {datetime.now().strftime('%H:%M:%S')}")

    def apply_theme(self, theme: str) -> None:
        self.theme = theme
        app = self.parent() if self.parent() else None
        from PySide6.QtWidgets import QApplication

        QApplication.instance().setStyleSheet(stylesheet_for(theme))

    def _maybe_prompt_first_run_ecri_login(self) -> None:
        already_prompted = self.context.db.query_one(
            "SELECT value FROM app_settings WHERE key = 'ecri_first_run_prompted'"
        )
        if already_prompted or self.context.credential_service.has_credentials(ECRI_SERVICE_NAME):
            return

        self.context.db.execute(
            "INSERT OR REPLACE INTO app_settings (key, value, updated_at) VALUES (?,?,?)",
            ("ecri_first_run_prompted", "true", datetime.now().isoformat()),
        )
        dialog = LoginDialog(ECRI_SERVICE_NAME, self.context.credential_service, self)
        dialog.exec()
