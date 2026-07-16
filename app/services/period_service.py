"""
Weekly check period calculation (FUNCTION 5).

Given a month/year, the hospital's weekly recall-monitoring cadence is:
    Week 1: day 1-7
    Week 2: day 8-14
    Week 3: day 15-21
    Week 4: day 22-end of month (28/29/30/31 depending on month)
"""

from __future__ import annotations

import calendar
from datetime import date

from app.models.period import ReportPeriod

_WEEK_BOUNDARIES = ((1, 7), (8, 14), (15, 21), (22, None))  # None -> end of month


def get_period(year: int, month: int, week_number: int) -> ReportPeriod:
    """Return the `ReportPeriod` for the given year/month/week (1-4)."""
    if not (1 <= week_number <= 4):
        raise ValueError("week_number must be between 1 and 4")

    start_day, end_day = _WEEK_BOUNDARIES[week_number - 1]
    last_day_of_month = calendar.monthrange(year, month)[1]
    end_day = end_day if end_day is not None else last_day_of_month
    end_day = min(end_day, last_day_of_month)

    return ReportPeriod(
        year=year,
        month=month,
        week_number=week_number,
        start_date=date(year, month, start_day),
        end_date=date(year, month, end_day),
    )


def get_all_periods(year: int, month: int) -> list[ReportPeriod]:
    """Return all four weekly periods for the given month/year."""
    return [get_period(year, month, w) for w in (1, 2, 3, 4)]


def get_period_for_date(target: date) -> ReportPeriod:
    """Return whichever weekly period contains `target`."""
    if target.day <= 7:
        week_number = 1
    elif target.day <= 14:
        week_number = 2
    elif target.day <= 21:
        week_number = 3
    else:
        week_number = 4
    return get_period(target.year, target.month, week_number)


def get_current_period() -> ReportPeriod:
    """Return the weekly period containing today's date - used by the scheduler."""
    return get_period_for_date(date.today())
