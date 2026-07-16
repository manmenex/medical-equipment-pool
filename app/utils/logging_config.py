"""
Centralized logging configuration.

Requirements addressed (FUNCTION 11 - LOGGING):
    - Logs are stored by day (one file per calendar day, auto-rotated at
      midnight, retained for 90 days).
    - Distinct named loggers exist for each auditable action category:
      login, download, import, matching, error, export - all in
      addition to normal module-level loggers, so the audit trail can be
      filtered independently of general debug noise.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_CONFIGURED = False

# Named audit-trail loggers required by the spec. Modules should fetch these
# via `get_audit_logger("login")` etc. rather than constructing their own.
AUDIT_CATEGORIES = ("login", "download", "import", "matching", "error", "export")


def configure_logging(log_dir: Path, level: str = "INFO") -> None:
    """Configure the root logger + per-category audit loggers.

    Safe to call multiple times; only configures handlers once per process.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Daily-rotating file for all application logs.
    app_handler = logging.handlers.TimedRotatingFileHandler(
        log_dir / "app.log", when="midnight", backupCount=90, encoding="utf-8", utc=False
    )
    app_handler.suffix = "%Y-%m-%d"
    app_handler.setFormatter(formatter)
    root_logger.addHandler(app_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # One dedicated, daily-rotating file per audit category, e.g. logs/login.log.
    for category in AUDIT_CATEGORIES:
        logger = logging.getLogger(f"audit.{category}")
        logger.setLevel(logging.INFO)
        logger.propagate = True  # also flows into app.log
        handler = logging.handlers.TimedRotatingFileHandler(
            log_dir / f"{category}.log", when="midnight", backupCount=90, encoding="utf-8", utc=False
        )
        handler.suffix = "%Y-%m-%d"
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    _CONFIGURED = True
    logging.getLogger(__name__).info("Logging configured (level=%s, dir=%s)", level, log_dir)


def get_logger(name: str) -> logging.Logger:
    """Standard module logger, e.g. `get_logger(__name__)`."""
    return logging.getLogger(name)


def get_audit_logger(category: str) -> logging.Logger:
    """Return one of the fixed audit-trail loggers.

    Parameters
    ----------
    category:
        One of `AUDIT_CATEGORIES` ("login", "download", "import",
        "matching", "error", "export").
    """
    if category not in AUDIT_CATEGORIES:
        raise ValueError(f"Unknown audit category '{category}'. Expected one of {AUDIT_CATEGORIES}")
    return logging.getLogger(f"audit.{category}")
