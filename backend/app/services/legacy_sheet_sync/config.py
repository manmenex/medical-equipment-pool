"""Configuration for the demo-only legacy pool sheet shadow sync.

Governance 2026-10-21 (docs/DECISION_LOG.md): temporary, disabled by default,
read-only, must be switched off before Production go-live. Read straight from
the environment (not ``app.core.config.Settings``) so the web application's
configuration is untouched and nothing here can affect it.

The key file PATH is configuration, not a secret, but it is still never
logged or put in an error message (``SyncConfigError`` messages are fixed
text) so nothing about where the credential lives leaks into logs.
"""
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

ENV_ENABLED = "LEGACY_SHEET_SYNC_ENABLED"
ENV_KEY_FILE = "LEGACY_SHEET_SYNC_KEY_FILE"
ENV_SPREADSHEET_ID = "LEGACY_SHEET_SYNC_SPREADSHEET_ID"
ENV_INTERVAL = "LEGACY_SHEET_SYNC_INTERVAL_SECONDS"
ENV_START = "LEGACY_SHEET_SYNC_START_DATE"
ENV_EMPLOYEE_CODE = "LEGACY_SHEET_SYNC_EMPLOYEE_CODE"

DEFAULT_INTERVAL_SECONDS = 300
MIN_INTERVAL_SECONDS = 60
DEFAULT_EMPLOYEE_CODE = "LEGACY-SYNC"
DEFAULT_BACKFILL_DAYS = 7  # the ledger's OP_TOO_OLD window

# Thailand has no daylight saving; a fixed offset avoids needing tzdata in
# the container image.
BANGKOK = timezone(timedelta(hours=7), "Asia/Bangkok")

TAB_DISPATCH = "ข้อมูลส่งเครื่องมือ"
TAB_RECEIPT = "ข้อมูลรับเครื่องมือ"

_TRUE = {"1", "true", "yes", "on"}


class SyncConfigError(RuntimeError):
    """Configuration problem. The message is fixed text: it never carries
    the key file path or any file content."""


@dataclass(frozen=True)
class SyncConfig:
    enabled: bool
    key_file: str | None
    spreadsheet_id: str | None
    interval_seconds: int
    start_override: datetime | None  # UTC; None = rolling now-7d
    employee_code: str

    def backfill_start(self, now: datetime | None = None) -> datetime:
        """Rows that occurred before this instant (UTC) are not imported.

        Default: now - 7 days, because the sync ledger sends anything older
        to the review list as OP_TOO_OLD. An earlier configured start date is
        honoured, and those older rows then land in review by design."""
        if self.start_override is not None:
            return self.start_override
        now = now or datetime.now(timezone.utc)
        return now - timedelta(days=DEFAULT_BACKFILL_DAYS)

    def require_source(self) -> None:
        if not self.key_file:
            raise SyncConfigError(f"{ENV_KEY_FILE} is not set.")
        if not self.spreadsheet_id:
            raise SyncConfigError(f"{ENV_SPREADSHEET_ID} is not set.")


def _parse_start(raw: str) -> datetime:
    raw = raw.strip()
    try:
        if len(raw) == 10:
            d = date.fromisoformat(raw)
            return datetime(d.year, d.month, d.day, tzinfo=BANGKOK).astimezone(timezone.utc)
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise SyncConfigError(f"{ENV_START} must be YYYY-MM-DD or an ISO-8601 datetime.") from None
    return (dt if dt.tzinfo else dt.replace(tzinfo=BANGKOK)).astimezone(timezone.utc)


def load_config(env: dict[str, str] | None = None) -> SyncConfig:
    env = os.environ if env is None else env
    try:
        interval = int(env.get(ENV_INTERVAL, "") or DEFAULT_INTERVAL_SECONDS)
    except ValueError:
        raise SyncConfigError(f"{ENV_INTERVAL} must be an integer.") from None
    start_raw = (env.get(ENV_START) or "").strip()
    return SyncConfig(
        enabled=(env.get(ENV_ENABLED) or "").strip().lower() in _TRUE,
        key_file=(env.get(ENV_KEY_FILE) or "").strip() or None,
        spreadsheet_id=(env.get(ENV_SPREADSHEET_ID) or "").strip() or None,
        interval_seconds=max(interval, MIN_INTERVAL_SECONDS),
        start_override=_parse_start(start_raw) if start_raw else None,
        employee_code=(env.get(ENV_EMPLOYEE_CODE) or "").strip() or DEFAULT_EMPLOYEE_CODE,
    )
