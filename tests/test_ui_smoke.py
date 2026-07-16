"""
GUI smoke test: build the full `AppContext` + `MainWindow` and switch
through every page once. Runs with the Qt "offscreen" platform plugin so
it works in headless CI without a real display.

Skipped automatically if PySide6 (or its native Qt libraries) aren't
available in the current environment.
"""

from __future__ import annotations

import os
from datetime import datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pyside6 = pytest.importorskip("PySide6", reason="PySide6 not installed in this environment")

from app.config.settings import load_settings  # noqa: E402
from app.services.app_context import build_app_context  # noqa: E402


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_main_window_builds_and_shows_all_pages(tmp_path, qapp, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"DATA_DIR={tmp_path}/data\n"
        f"LOG_DIR={tmp_path}/logs\n"
        f"DOWNLOAD_DIR={tmp_path}/downloads\n"
        f"BACKUP_DIR={tmp_path}/backups\n"
        f"DATABASE_PATH={tmp_path}/data/test.db\n"
        "SCHEDULER_ENABLED=false\n"
    )
    settings = load_settings(env_file=env_file)
    context = build_app_context(settings)

    # Pre-mark the ECRI first-run prompt as shown so MainWindow doesn't pop
    # a blocking modal QDialog during this headless, unattended test.
    context.db.execute(
        "INSERT OR REPLACE INTO app_settings (key, value, updated_at) VALUES (?,?,?)",
        ("ecri_first_run_prompted", "true", datetime.now().isoformat()),
    )

    from app.ui.main_window import MainWindow

    window = MainWindow(context, scheduler_manager=None)
    window.show()

    for key in ("dashboard", "fda", "ecri", "inventory", "matching", "search", "reports", "settings"):
        window._show_page(key)
        assert window.stack.currentWidget() is window.pages[key]

    context.db.close()
