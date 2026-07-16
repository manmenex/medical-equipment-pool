"""Weekly reporting period model (FUNCTION 5)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(slots=True, frozen=True)
class ReportPeriod:
    """A Week-N period within a given month/year.

    Week 1: day 1-7, Week 2: day 8-14, Week 3: day 15-21,
    Week 4: day 22-end of month.
    """

    year: int
    month: int
    week_number: int  # 1-4
    start_date: date
    end_date: date

    @property
    def label(self) -> str:
        return f"{self.year}_Week{self.week_number}"

    @property
    def month_name(self) -> str:
        return self.start_date.strftime("%B")
