"""Regression tests for app.models.mixins.UTCDateTime's two invariants
(Roadmap PR15B design-compliance follow-up, docs/design/
PR15B_SCHEMA_HYGIENE_PLAN.md §3.7.5):

1. **Write side (fail closed):** this application writes UTC only -- every
   Python-side value ever bound to a `UTCDateTime` column is constructed as
   `datetime.now(timezone.utc)`. A non-UTC aware datetime is rejected
   outright at bind time rather than silently normalized, since silently
   converting it would hide a real bug (something computed a wall-clock
   value in the wrong zone before handing it to the ORM). A naive value is
   passed through unchanged -- assumed UTC per this column's convention.
2. **Read side (SQLite/PostgreSQL parity):** SQLite has no native
   `timestamptz` type and silently drops `tzinfo` on read; PostgreSQL's
   `timestamptz` always returns aware datetimes. `UTCDateTime` reattaches
   `tzinfo=timezone.utc` on SQLite specifically, so both dialects' test
   suites verify the same thing.

These tests exercise the type directly against the SQLite test database
(the default suite's dialect) using `AuditLog.created_at`, a
`UTCDateTime`-typed column with a Python-side default.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.audit import AuditLog


async def test_utc_aware_datetime_is_accepted_and_round_trips_aware(db_session):
    value = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    log = AuditLog(action="test", entity_type="test", created_at=value)
    db_session.add(log)
    await db_session.commit()

    assert log.created_at == value
    assert log.created_at.tzinfo is not None

    fetched = (await db_session.execute(select(AuditLog).where(AuditLog.id == log.id))).scalar_one()
    assert fetched.created_at == value
    assert fetched.created_at.tzinfo is not None, (
        "a value re-fetched from the database must still be timezone-aware -- this is exactly "
        "the SQLite tzinfo-loss gap UTCDateTime closes"
    )


async def test_naive_datetime_is_accepted_unchanged_assumed_utc(db_session):
    """A naive value is not rejected -- it is assumed UTC per this
    column's convention (the same assumption applied to a value already
    round-tripped through SQLite, which is naive until read back)."""
    value = datetime(2026, 6, 1, 12, 0, 0)
    log = AuditLog(action="test", entity_type="test", created_at=value)
    db_session.add(log)
    await db_session.commit()

    assert log.created_at.replace(tzinfo=None) == value


@pytest.mark.parametrize(
    "offset_hours",
    [7, -5, 1],
)
async def test_non_utc_aware_datetime_is_rejected_at_bind_time(db_session, offset_hours):
    """The core write-side invariant: a non-UTC aware datetime must never
    be silently normalized to UTC -- it is rejected outright, since a
    non-UTC value reaching this column indicates a real bug elsewhere
    (this application has no legitimate reason to construct one)."""
    non_utc = timezone(timedelta(hours=offset_hours))
    value = datetime(2026, 6, 1, 12, 0, 0, tzinfo=non_utc)
    log = AuditLog(action="test", entity_type="test", created_at=value)
    db_session.add(log)

    with pytest.raises(Exception) as exc_info:
        await db_session.commit()

    assert "UTC" in str(exc_info.value), (
        f"the rejection must explain the UTC-only invariant, got: {exc_info.value}"
    )
    await db_session.rollback()


async def test_utc_aware_datetime_with_zero_offset_non_utc_tzinfo_is_accepted():
    """A `timezone.utc`-equivalent but differently-constructed tzinfo
    (offset of exactly zero, e.g. `timezone(timedelta(0))`) must be
    accepted -- the invariant is about the *offset* being UTC (zero), not
    about `tzinfo is timezone.utc` by identity."""
    from app.models.mixins import UTCDateTime

    utc_like = timezone(timedelta(0))
    value = datetime(2026, 6, 1, 12, 0, 0, tzinfo=utc_like)

    coerced = UTCDateTime().process_bind_param(value, dialect=None)
    assert coerced == value
