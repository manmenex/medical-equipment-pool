"""
Background task runner for the Qt GUI.

Every long-running operation (scraping, importing, matching, report
generation) must run off the GUI thread or the window would freeze and
the OS would flag it as unresponsive. `Worker` runs an arbitrary callable
on a `QThread` and reports back via signals so pages can update a
QProgressBar / QStatusBar and show `AppError` messages in plain language
instead of a raw traceback (FUNCTION 12 - ERROR HANDLING).
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QThread, Signal

from app.utils.exceptions import AppError
from app.utils.logging_config import get_audit_logger, get_logger

logger = get_logger(__name__)
audit_error = get_audit_logger("error")


class Worker(QThread):
    """Runs `fn(*args, **kwargs)` on a background thread.

    Signals
    -------
    finished(object): emitted with the callable's return value on success.
    failed(str): emitted with a user-friendly message if `fn` raises.
    """

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[..., Any], *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.finished.emit(result)
        except AppError as exc:
            logger.error("Worker task failed: %s", exc)
            audit_error.error("%s", exc)
            self.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover - defensive catch-all
            logger.exception("Worker task failed unexpectedly")
            audit_error.exception("Unexpected worker failure")
            self.failed.emit(f"Unexpected error: {exc}")
