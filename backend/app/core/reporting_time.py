"""Roadmap PR16 (Reporting Foundation) business_date/shift derivation.

Computed, never persisted (docs/design/PR16_REPORTING_FOUNDATION_PLAN.md §6,
Option A) -- no migration, no new column. `business_date_and_shift()` is the
pure-Python reference implementation; `business_date_and_shift_sql()` is its
SQLAlchemy-expression twin for use inside `crud/transaction.py`'s
`select()`/`WHERE` clauses. Both are tested against each other
(backend/tests/test_reporting_time.py) so they can never silently diverge.

Boundary policy (`_SHIFT_BOUNDARY_POLICY`) is Roadmap PR16 Owner Decision #1,
confirmed by the Repository Owner and recorded in `docs/DECISION_LOG.md`
("Roadmap PR16 -- Owner Decision #1"): Day shift 08:00-20:00 `Asia/Bangkok`,
Night shift 20:00-08:00, `business_date_anchor = shift_start_date` (an
overnight Night shift's post-midnight instants take the shift's *start*
date), `on_demand` dispatches classified identically to `RoutineRound`-tied
ones -- this module has no special case for `on_demand`, it only ever
receives a UTC instant.
"""

import enum
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import Date, DateTime, String, case, literal
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import ColumnElement

# Thailand has used a single, DST-free UTC+7 offset since 1920 -- there is no
# historical or future transition to account for.
_BANGKOK_TZ = ZoneInfo("Asia/Bangkok")


class Shift(str, enum.Enum):
    """Mirrors the existing `(str, enum.Enum)` shape already used by
    `TransactionStatus`/`DispatchType`/`RoutineRound` for consistency, even
    though this one never backs a database column (same non-column
    precedent as `ReceiptOutcome`)."""

    DAY = "day"
    NIGHT = "night"


@dataclass(frozen=True)
class _ShiftBoundaryPolicy:
    day_start_local: time
    night_start_local: time
    business_date_anchor: Literal["shift_start_date", "instant_calendar_date"]
    # "shift_start_date": every instant within a shift, including the
    # post-midnight portion of an overnight Night shift, takes the calendar
    # date the shift *started* on.
    # "instant_calendar_date": business_date is simply the Asia/Bangkok
    # calendar date of the instant itself.
    # These two rules disagree for exactly the post-midnight portion of an
    # overnight shift -- confirmed by Owner Decision #1, not a default.


# Roadmap PR16 Owner Decision #1 (docs/DECISION_LOG.md).
_SHIFT_BOUNDARY_POLICY = _ShiftBoundaryPolicy(
    day_start_local=time(8, 0),
    night_start_local=time(20, 0),
    business_date_anchor="shift_start_date",
)


def _shift_for_time(t: time) -> Shift:
    policy = _SHIFT_BOUNDARY_POLICY
    if policy.day_start_local <= t < policy.night_start_local:
        return Shift.DAY
    return Shift.NIGHT


def classify(ts_local: datetime) -> tuple[date, Shift]:
    """Classifies a naive Asia/Bangkok local timestamp into (business_date,
    shift). Covers all 24 hours of the day (both the Night->Day and
    Day->Night transitions), not one boundary hour."""
    policy = _SHIFT_BOUNDARY_POLICY
    shift = _shift_for_time(ts_local.time())
    if policy.business_date_anchor == "instant_calendar_date":
        business_date = ts_local.date()
    else:  # "shift_start_date"
        day_start_delta = timedelta(
            hours=policy.day_start_local.hour,
            minutes=policy.day_start_local.minute,
            seconds=policy.day_start_local.second,
        )
        business_date = (ts_local - day_start_delta).date()
    return business_date, shift


def business_date_and_shift(ts: datetime) -> tuple[date, Shift]:
    """Pure-Python reference derivation from an aware UTC datetime (matching
    `UTCDateTime`'s existing contract -- see
    docs/design/PR16_REPORTING_FOUNDATION_PLAN.md §11)."""
    if ts.tzinfo is None or ts.utcoffset() != timedelta(0):
        raise ValueError(
            f"business_date_and_shift() requires an aware UTC datetime, got {ts!r}. "
            "Every timestamp this derivation reads (BorrowTransaction.borrowed_at/"
            "returned_at) is already UTCDateTime-normalized to aware UTC."
        )
    ts_local = ts.astimezone(_BANGKOK_TZ).replace(tzinfo=None)
    return classify(ts_local)


class _BangkokLocalTimestamp(ColumnElement):
    """Asia/Bangkok local wall-clock naive timestamp for an aware UTC column."""

    inherit_cache = True
    type = DateTime()

    def __init__(self, column):
        self.column = column


@compiles(_BangkokLocalTimestamp, "postgresql")
def _compile_bkk_local_ts_postgresql(element, compiler, **kw):
    return "(%s AT TIME ZONE 'Asia/Bangkok')" % compiler.process(element.column, **kw)


@compiles(_BangkokLocalTimestamp)
def _compile_bkk_local_ts_default(element, compiler, **kw):
    # SQLite fallback for the fast non-PostgreSQL test suite only -- SQLite
    # has no IANA timezone support. Asia/Bangkok's fixed, DST-free UTC+7
    # offset (see module docstring) makes a literal +7 hour shift exactly
    # equivalent to the PostgreSQL AT TIME ZONE conversion above for every
    # representable timestamp; verified against a live PostgreSQL 16
    # instance in backend/tests/test_postgres_integration.py.
    return "datetime(%s, '+7 hours')" % compiler.process(element.column, **kw)


class _BangkokTimeOfDay(ColumnElement):
    """HH:MM:SS text of the Asia/Bangkok local wall-clock time -- zero-padded
    HH:MM:SS compares correctly as text, giving a portable boundary
    comparison without relying on cross-dialect date/time arithmetic."""

    inherit_cache = True
    type = String()

    def __init__(self, column):
        self.column = column


@compiles(_BangkokTimeOfDay, "postgresql")
def _compile_bkk_tod_postgresql(element, compiler, **kw):
    return "to_char(%s AT TIME ZONE 'Asia/Bangkok', 'HH24:MI:SS')" % compiler.process(
        element.column, **kw
    )


@compiles(_BangkokTimeOfDay)
def _compile_bkk_tod_default(element, compiler, **kw):
    return "strftime('%%H:%%M:%%S', %s, '+7 hours')" % compiler.process(element.column, **kw)


class _BangkokBusinessDate(ColumnElement):
    """The `business_date` for `_SHIFT_BOUNDARY_POLICY`'s confirmed anchor,
    from an aware UTC column."""

    inherit_cache = True
    type = Date()

    def __init__(self, column):
        self.column = column


@compiles(_BangkokBusinessDate, "postgresql")
def _compile_bkk_business_date_postgresql(element, compiler, **kw):
    policy = _SHIFT_BOUNDARY_POLICY
    col_sql = compiler.process(element.column, **kw)
    if policy.business_date_anchor == "instant_calendar_date":
        return "CAST(%s AT TIME ZONE 'Asia/Bangkok' AS date)" % col_sql
    interval = "%d hours %d minutes %d seconds" % (
        policy.day_start_local.hour,
        policy.day_start_local.minute,
        policy.day_start_local.second,
    )
    return "CAST((%s AT TIME ZONE 'Asia/Bangkok') - INTERVAL '%s' AS date)" % (col_sql, interval)


@compiles(_BangkokBusinessDate)
def _compile_bkk_business_date_default(element, compiler, **kw):
    policy = _SHIFT_BOUNDARY_POLICY
    col_sql = compiler.process(element.column, **kw)
    if policy.business_date_anchor == "instant_calendar_date":
        return "date(%s, '+7 hours')" % col_sql
    return "date(%s, '+7 hours', '-%d hours', '-%d minutes', '-%d seconds')" % (
        col_sql,
        policy.day_start_local.hour,
        policy.day_start_local.minute,
        policy.day_start_local.second,
    )


def business_date_and_shift_sql(column) -> tuple[ColumnElement, ColumnElement]:
    """SQLAlchemy-expression twin of `business_date_and_shift()`, for use
    inside `crud/transaction.py`'s `select()`/`WHERE` clauses. Built from the
    identical boundary policy, tested against the pure-Python function for
    parity (backend/tests/test_reporting_time.py)."""
    policy = _SHIFT_BOUNDARY_POLICY
    tod = _BangkokTimeOfDay(column)
    day_start_str = policy.day_start_local.strftime("%H:%M:%S")
    night_start_str = policy.night_start_local.strftime("%H:%M:%S")
    shift_expr = case(
        ((tod >= day_start_str) & (tod < night_start_str), literal(Shift.DAY.value)),
        else_=literal(Shift.NIGHT.value),
    )
    business_date_expr = _BangkokBusinessDate(column)
    return business_date_expr, shift_expr
