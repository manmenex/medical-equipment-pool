"""Data models for recall/alert records collected from FDA and ECRI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

from app.models.enums import RecallSource


@dataclass(slots=True)
class FDARecall:
    """One row scraped/pulled from the FDA CDRH recall database.

    Field names mirror the columns available on the public FDA recall
    search (res.cfm) and the openFDA `device/recall` endpoint used as a
    resilient fallback data source (see app/scraper/fda.py).
    """

    recall_number: str
    recall_class: str = ""             # Class I / II / III
    product: str = ""
    product_code: str = ""
    manufacturer: str = ""
    reason: str = ""
    date_initiated: Optional[date] = None
    date_posted: Optional[date] = None
    date_terminated: Optional[date] = None
    status: str = ""                   # Ongoing / Terminated / Completed
    distribution: str = ""
    quantity: str = ""
    model_number: str = ""
    catalog_number: str = ""
    udi: str = ""
    k_numbers: str = ""
    event_id: str = ""
    recall_url: str = ""
    root_cause: str = ""
    action_taken: str = ""
    raw_data: dict[str, Any] = field(default_factory=dict)
    fetched_at: datetime = field(default_factory=datetime.now)

    id: Optional[int] = None

    @property
    def source(self) -> RecallSource:
        return RecallSource.FDA

    def natural_key(self) -> str:
        """Stable key used for de-duplication on import."""
        return f"FDA::{self.recall_number}"


@dataclass(slots=True)
class ECRIAlert:
    """One alert/recall row scraped from the ECRI Alerts Tracker (STS).

    ECRI's portal layout is subscription-gated and not publicly
    documented, so beyond the well-known fields below, every column found
    on the page is preserved verbatim in `raw_data` (JSON) to satisfy the
    "collect every available field" requirement without hardcoding a
    brittle, incomplete schema.
    """

    alert_number: str
    title: str = ""
    manufacturer: str = ""
    product: str = ""
    model_number: str = ""
    catalog_number: str = ""
    hazard_level: str = ""
    alert_type: str = ""
    date_issued: Optional[date] = None
    status: str = ""
    summary: str = ""
    alert_url: str = ""
    raw_data: dict[str, Any] = field(default_factory=dict)
    fetched_at: datetime = field(default_factory=datetime.now)

    id: Optional[int] = None

    @property
    def source(self) -> RecallSource:
        return RecallSource.ECRI

    def natural_key(self) -> str:
        return f"ECRI::{self.alert_number}"
