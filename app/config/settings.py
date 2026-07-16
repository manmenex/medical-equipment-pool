"""
Application configuration.

All configuration is sourced from a `.env` file (see `.env.example`) so that
no secrets or environment-specific paths are hardcoded in source control.
`Settings` is a frozen dataclass - once loaded it is treated as read-only for
the lifetime of the process. Call `get_settings(force_reload=True)` after the
user changes something in the Settings page that requires a re-read.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


def _app_root() -> Path:
    """Return the application root directory.

    When frozen by PyInstaller, resources live next to the executable
    (``sys.executable``); in normal development they live at the repo root
    (two levels above this file: app/config/settings.py -> repo root).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


def _float(value: str | None, default: float) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except ValueError:
        return default


def _list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    """Strongly-typed application settings, loaded once at startup."""

    app_root: Path
    app_env: str
    app_name: str
    log_level: str
    log_dir: Path
    data_dir: Path
    download_dir: Path
    backup_dir: Path

    database_path: Path

    fda_search_url: str
    fda_openfda_api_url: str
    fda_use_openfda_fallback: bool
    fda_request_timeout_ms: int

    ecri_login_url: str
    ecri_alerts_url: str
    ecri_request_timeout_ms: int

    playwright_headless: bool
    playwright_browser: str

    fuzzy_match_threshold: float
    possible_match_threshold: float

    scheduler_enabled: bool
    scheduler_frequency: str
    scheduler_hour: int
    scheduler_minute: int

    smtp_host: str
    smtp_port: int
    smtp_use_tls: bool
    smtp_from_address: str
    email_report_recipients: list[str] = field(default_factory=list)

    ui_theme: str = "dark"

    def ensure_directories(self) -> None:
        """Create all working directories the app relies on, if missing."""
        for directory in (
            self.log_dir,
            self.data_dir,
            self.download_dir,
            self.backup_dir,
            self.database_path.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def _resolve(root: Path, value: str) -> Path:
    """Resolve a possibly-relative path from .env against the app root."""
    path = Path(value)
    return path if path.is_absolute() else (root / path).resolve()


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Load settings from the environment / a .env file.

    Parameters
    ----------
    env_file:
        Optional explicit path to an env file. Defaults to ``<app_root>/.env``.
    """
    root = _app_root()
    dotenv_path = Path(env_file) if env_file else root / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path=dotenv_path, override=False)

    env = os.environ

    settings = Settings(
        app_root=root,
        app_env=env.get("APP_ENV", "development"),
        app_name=env.get("APP_NAME", "Medical Device Recall Monitor"),
        log_level=env.get("LOG_LEVEL", "INFO").upper(),
        log_dir=_resolve(root, env.get("LOG_DIR", "./logs")),
        data_dir=_resolve(root, env.get("DATA_DIR", "./data")),
        download_dir=_resolve(root, env.get("DOWNLOAD_DIR", "./downloads")),
        backup_dir=_resolve(root, env.get("BACKUP_DIR", "./backups")),
        database_path=_resolve(root, env.get("DATABASE_PATH", "./data/recall_monitor.db")),
        fda_search_url=env.get(
            "FDA_SEARCH_URL",
            "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfres/res.cfm",
        ),
        fda_openfda_api_url=env.get("FDA_OPENFDA_API_URL", "https://api.fda.gov/device/recall.json"),
        fda_use_openfda_fallback=_bool(env.get("FDA_USE_OPENFDA_FALLBACK"), True),
        fda_request_timeout_ms=_int(env.get("FDA_REQUEST_TIMEOUT_MS"), 30000),
        ecri_login_url=env.get("ECRI_LOGIN_URL", "https://sts.ecri.org/"),
        ecri_alerts_url=env.get("ECRI_ALERTS_URL", "https://sts.ecri.org/alerts"),
        ecri_request_timeout_ms=_int(env.get("ECRI_REQUEST_TIMEOUT_MS"), 30000),
        playwright_headless=_bool(env.get("PLAYWRIGHT_HEADLESS"), True),
        playwright_browser=env.get("PLAYWRIGHT_BROWSER", "chromium"),
        fuzzy_match_threshold=_float(env.get("FUZZY_MATCH_THRESHOLD"), 90.0),
        possible_match_threshold=_float(env.get("POSSIBLE_MATCH_THRESHOLD"), 75.0),
        scheduler_enabled=_bool(env.get("SCHEDULER_ENABLED"), True),
        scheduler_frequency=env.get("SCHEDULER_FREQUENCY", "weekly"),
        scheduler_hour=_int(env.get("SCHEDULER_HOUR"), 6),
        scheduler_minute=_int(env.get("SCHEDULER_MINUTE"), 0),
        smtp_host=env.get("SMTP_HOST", ""),
        smtp_port=_int(env.get("SMTP_PORT"), 587),
        smtp_use_tls=_bool(env.get("SMTP_USE_TLS"), True),
        smtp_from_address=env.get("SMTP_FROM_ADDRESS", ""),
        email_report_recipients=_list(env.get("EMAIL_REPORT_RECIPIENTS")),
        ui_theme=env.get("UI_THEME", "dark"),
    )
    settings.ensure_directories()
    return settings


@lru_cache(maxsize=1)
def _cached_settings() -> Settings:
    return load_settings()


def get_settings(force_reload: bool = False) -> Settings:
    """Return the process-wide Settings singleton (cached)."""
    if force_reload:
        _cached_settings.cache_clear()
    return _cached_settings()
