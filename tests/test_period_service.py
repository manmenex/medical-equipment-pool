from datetime import date

import pytest

from app.services.period_service import get_all_periods, get_period, get_period_for_date


def test_week_boundaries_for_31_day_month():
    periods = get_all_periods(2026, 1)  # January has 31 days
    assert [p.start_date.day for p in periods] == [1, 8, 15, 22]
    assert [p.end_date.day for p in periods] == [7, 14, 21, 31]


def test_week_boundaries_for_28_day_month():
    periods = get_all_periods(2026, 2)  # 2026 is not a leap year -> Feb has 28 days
    assert periods[3].end_date.day == 28


def test_week_boundaries_for_leap_february():
    periods = get_all_periods(2024, 2)  # 2024 is a leap year -> Feb has 29 days
    assert periods[3].end_date.day == 29


def test_labels():
    p = get_period(2026, 7, 2)
    assert p.label == "2026_Week2"


def test_invalid_week_number_raises():
    with pytest.raises(ValueError):
        get_period(2026, 1, 5)


def test_get_period_for_date():
    assert get_period_for_date(date(2026, 7, 5)).week_number == 1
    assert get_period_for_date(date(2026, 7, 10)).week_number == 2
    assert get_period_for_date(date(2026, 7, 18)).week_number == 3
    assert get_period_for_date(date(2026, 7, 30)).week_number == 4
