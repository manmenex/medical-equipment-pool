"""Matching engine result model (FUNCTION 4)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional

from app.models.enums import MatchMethod, MatchStatus, RecallSource


@dataclass(slots=True)
class MatchResult:
    """The outcome of comparing one recall record to one inventory item."""

    recall_source: RecallSource
    recall_number: str
    hospital_asset_number: str
    manufacturer: str
    model: str
    confidence_score: float          # 0-100
    status: MatchStatus
    method: MatchMethod
    reason: str = ""
    recall_id: Optional[int] = None
    inventory_id: Optional[int] = None
    checked_at: datetime = None  # type: ignore[assignment]
    report_period_start: Optional[date] = None
    report_period_end: Optional[date] = None

    id: Optional[int] = None

    def __post_init__(self) -> None:
        if self.checked_at is None:
            self.checked_at = datetime.now()
