"""Aggregate container passed to the Excel/PDF report renderers."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.match import MatchResult
from app.models.period import ReportPeriod
from app.models.recall import ECRIAlert, FDARecall


@dataclass
class ReportData:
    period: ReportPeriod
    fda_recalls: list[FDARecall] = field(default_factory=list)
    ecri_alerts: list[ECRIAlert] = field(default_factory=list)
    match_results: list[MatchResult] = field(default_factory=list)

    @property
    def total_fda(self) -> int:
        return len(self.fda_recalls)

    @property
    def total_ecri(self) -> int:
        return len(self.ecri_alerts)

    @property
    def total_matched(self) -> int:
        return sum(1 for m in self.match_results if m.status.value == "Matched")

    @property
    def total_possible(self) -> int:
        return sum(1 for m in self.match_results if m.status.value == "Possible Match")

    @property
    def total_not_matched(self) -> int:
        return sum(1 for m in self.match_results if m.status.value == "Not Matched")
