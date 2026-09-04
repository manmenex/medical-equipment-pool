import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """`DateTime(timezone=True)` that round-trips consistently across
    PostgreSQL and SQLite, and enforces this application's "UTC only"
    invariant at bind time (Roadmap PR15B,
    docs/design/PR15B_SCHEMA_HYGIENE_PLAN.md §3.7.5).

    **Read side (cross-dialect round-trip):** PostgreSQL's `timestamptz`
    always returns timezone-aware datetimes. SQLite has no native
    `timestamptz` type -- `sa.DateTime(timezone=True)` stores an aware
    value's ISO string (including its offset) but the SQLite dialect's
    result processor does not re-attach `tzinfo` on read, silently handing
    back a naive datetime. Every timestamptz column in this schema
    represents a UTC instant by convention (§3.2/§3.4), so on SQLite
    specifically this reattaches `tzinfo=timezone.utc` to whatever naive
    value comes back, making the two dialects' test suites verify the same
    thing rather than silently diverging on what "the ORM object has
    tzinfo" even means.

    **Write side (fail closed, not silently normalize):** every Python-side
    value ever written into a `UTCDateTime` column in this codebase is
    already constructed as `datetime.now(timezone.utc)` -- there is no call
    site anywhere in `app/` that writes a differently-offset aware value.
    Rather than silently converting an aware-but-non-UTC value to UTC
    (which would hide a real bug -- something computed a wall-clock value
    in the wrong zone before handing it to the ORM), a non-UTC aware value
    is rejected outright at bind time, matching this project's established
    fail-closed convention (the migrations' own verify-and-no-op /
    fail-closed discipline, §8.7c). A naive value is passed through
    unchanged -- assumed UTC per this column's own convention, exactly as
    a value already round-tripped through SQLite is naive until the read
    side above reattaches `tzinfo`.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None and value.utcoffset() != timedelta(0):
            raise ValueError(
                f"UTCDateTime received a non-UTC aware datetime ({value!r}). This application "
                "writes UTC only (docs/design/PR15B_SCHEMA_HYGIENE_PLAN.md §3.2) -- convert to "
                "UTC explicitly (e.g. value.astimezone(timezone.utc)) before assigning it to this "
                "column; this type deliberately does not normalize a non-UTC value silently."
            )
        return value

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
