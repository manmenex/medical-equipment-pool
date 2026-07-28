import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """`DateTime(timezone=True)` that round-trips consistently across
    PostgreSQL and SQLite (Roadmap PR15B,
    docs/design/PR15B_SCHEMA_HYGIENE_PLAN.md §3.7.5).

    PostgreSQL's `timestamptz` always returns timezone-aware datetimes.
    SQLite has no native `timestamptz` type -- `sa.DateTime(timezone=True)`
    stores an aware value's ISO string (including its offset) but the
    SQLite dialect's result processor does not re-attach `tzinfo` on read,
    silently handing back a naive datetime. Every timestamptz column in
    this schema represents a UTC instant by convention (§3.2/§3.4), so on
    SQLite specifically this reattaches `tzinfo=timezone.utc` to whatever
    naive value comes back, making the two dialects' test suites verify
    the same thing rather than silently diverging on what "the ORM object
    has tzinfo" even means.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class UUIDPKMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
