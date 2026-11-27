from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.system_notes import clean_label

BKK = ZoneInfo("Asia/Bangkok")


def to_bkk(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        from datetime import timezone

        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BKK)


def format_bkk(dt: datetime | None) -> str | None:
    """dd/mm/yyyy HH:MM in Asia/Bangkok, or None."""
    local = to_bkk(dt)
    return local.strftime("%d/%m/%Y %H:%M") if local else None


def keyer_display(keyer_label: str | None, user_full_name: str | None) -> str | None:
    """BME label (system-note text stripped), falling back to the user's name.
    Same precedence the Monitor uses; the sync user's name is never shown
    when a label exists."""
    return clean_label(keyer_label) or clean_label(user_full_name)
