"""
Application entrypoint.

Boot sequence:
    1. Load configuration from `.env`.
    2. Configure logging (daily-rotating files under `LOG_DIR`).
    3. Build the `AppContext` (database + scraper + service wiring).
    4. Start the PySide6 GUI, applying the configured theme.
    5. Start the APScheduler-based background scheduler if enabled.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.config.settings import get_settings
from app.scheduler.jobs import SchedulerManager
from app.services.app_context import build_app_context
from app.ui.main_window import MainWindow
from app.ui.theme import stylesheet_for
from app.utils.logging_config import configure_logging, get_logger


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_dir, settings.log_level)
    logger = get_logger(__name__)
    logger.info("Starting %s (env=%s)", settings.app_name, settings.app_env)

    context = build_app_context(settings)

    app = QApplication(sys.argv)
    app.setApplicationName(settings.app_name)
    app.setStyleSheet(stylesheet_for(settings.ui_theme))

    scheduler_manager = SchedulerManager(context, notify=lambda msg: logger.info(msg))
    if settings.scheduler_enabled:
        scheduler_manager.configure(settings.scheduler_frequency, settings.scheduler_hour, settings.scheduler_minute)
        scheduler_manager.start()

    window = MainWindow(context, scheduler_manager)
    window.show()

    exit_code = app.exec()

    scheduler_manager.stop()
    context.db.close()
    logger.info("Application exited with code %s", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
