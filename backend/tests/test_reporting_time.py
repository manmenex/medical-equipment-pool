"""Regression tests for app.core.reporting_time (Roadmap PR16, Reporting
Foundation -- Implementation Slice 1).

Covers: both shift transitions, the midnight instant, business-date
rollover under the confirmed `shift_start_date` anchor (Owner Decision #1,
docs/DECISION_LOG.md), Asia/Bangkok conversion correctness, determinism,
the fail-closed non-UTC-aware guard, and SQL/Python parity -- the single
most important test this module requires, per docs/design/
PR16_REPORTING_FOUNDATION_PLAN.md §15.
"""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from app.core.reporting_time import Shift, business_date_and_shift, business_date_and_shift_sql
from app.models.audit import AuditLog

# (utc_instant, expected_business_date, expected_shift) -- covers both
# transitions (08:00/20:00 Asia/Bangkok), the midnight instant, and the
# shift_start_date rollover for the post-midnight portion of an overnight
# Night shift.
_CASES = [
    (datetime(2026, 7, 28, 0, 30, 0, tzinfo=timezone.utc), date(2026, 7, 27), Shift.NIGHT),
    (datetime(2026, 7, 27, 17, 0, 0, tzinfo=timezone.utc), date(2026, 7, 27), Shift.NIGHT),  # exact midnight Bangkok
    (datetime(2026, 7, 28, 0, 59, 59, tzinfo=timezone.utc), date(2026, 7, 27), Shift.NIGHT),  # 07:59:59 Bangkok
    (datetime(2026, 7, 28, 1, 0, 0, tzinfo=timezone.utc), date(2026, 7, 28), Shift.DAY),  # 08:00:00 Bangkok, Day start
    (datetime(2026, 7, 28, 12, 59, 59, tzinfo=timezone.utc), date(2026, 7, 28), Shift.DAY),  # 19:59:59 Bangkok
    (datetime(2026, 7, 28, 13, 0, 0, tzinfo=timezone.utc), date(2026, 7, 28), Shift.NIGHT),  # 20:00:00 Bangkok, Night start
    (datetime(2026, 7, 28, 16, 59, 59, tzinfo=timezone.utc), date(2026, 7, 28), Shift.NIGHT),  # 23:59:59 Bangkok
]


@pytest.mark.parametrize("utc_instant,expected_date,expected_shift", _CASES)
def test_business_date_and_shift_pure_function(utc_instant, expected_date, expected_shift):
    business_date, shift = business_date_and_shift(utc_instant)
    assert business_date == expected_date
    assert shift == expected_shift


def test_business_date_and_shift_is_deterministic():
    ts = datetime(2026, 7, 28, 5, 0, 0, tzinfo=timezone.utc)
    assert business_date_and_shift(ts) == business_date_and_shift(ts)


def test_business_date_and_shift_rejects_naive_datetime():
    with pytest.raises(ValueError):
        business_date_and_shift(datetime(2026, 7, 28, 5, 0, 0))


def test_business_date_and_shift_rejects_non_utc_aware_datetime():
    from datetime import timedelta, timezone as tz

    bangkok = tz(timedelta(hours=7))
    with pytest.raises(ValueError):
        business_date_and_shift(datetime(2026, 7, 28, 12, 0, 0, tzinfo=bangkok))


async def test_sql_python_parity(db_session):
    """The single most important test this design requires: the SQL twin
    and the pure-Python function must never silently diverge.

    Rows are matched back to `_CASES` by their (distinct) `created_at`
    value, not by insertion order -- `AuditLog.id` is a random UUID
    (UUIDPKMixin), so `ORDER BY id` does not preserve insertion order.
    """
    for utc_instant, expected_date, expected_shift in _CASES:
        db_session.add(AuditLog(action="test", entity_type="test", created_at=utc_instant))
    await db_session.commit()

    business_date_expr, shift_expr = business_date_and_shift_sql(AuditLog.created_at)
    rows = (await db_session.execute(select(AuditLog.created_at, business_date_expr, shift_expr))).all()
    by_created_at = {created_at.replace(tzinfo=timezone.utc): (bd, sh) for created_at, bd, sh in rows}

    assert len(rows) == len(_CASES)
    for utc_instant, expected_date, expected_shift in _CASES:
        sql_business_date, sql_shift = by_created_at[utc_instant]
        py_business_date, py_shift = business_date_and_shift(utc_instant)
        assert sql_business_date == py_business_date == expected_date
        assert Shift(sql_shift) == py_shift == expected_shift
