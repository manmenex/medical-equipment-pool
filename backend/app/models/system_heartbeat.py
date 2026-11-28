from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import UTCDateTime

HEARTBEAT_LEGACY_SHEET_SYNC = "legacy_sheet_sync"


class SystemHeartbeat(Base):
    """One row per background runner: the time of its last successful pass.
    Operational metadata only (read by the admin health banner)."""

    __tablename__ = "system_heartbeats"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    beat_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
