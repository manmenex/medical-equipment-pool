"""Persistence for `MatchResult` rows, kept separate from the (DB-free,
easily unit-tested) scoring logic in `matching_service.py`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from app.database.db import Database
from app.models.enums import MatchMethod, MatchStatus, RecallSource
from app.models.match import MatchResult
from app.utils.logging_config import get_audit_logger

audit_matching = get_audit_logger("matching")


class MatchRepository:
    def __init__(self, db: Database):
        self.db = db

    def save_all(self, results: list[MatchResult]) -> None:
        rows = [
            (
                r.recall_source.value,
                r.recall_id,
                r.recall_number,
                r.inventory_id,
                r.hospital_asset_number,
                r.manufacturer,
                r.model,
                r.confidence_score,
                r.status.value,
                r.method.value,
                r.reason,
                r.report_period_start.isoformat() if r.report_period_start else None,
                r.report_period_end.isoformat() if r.report_period_end else None,
                r.checked_at.isoformat(),
            )
            for r in results
        ]
        self.db.executemany(
            """
            INSERT INTO match_results (
                recall_source, recall_id, recall_number, inventory_id, hospital_asset_number,
                manufacturer, model, confidence_score, status, method, reason,
                report_period_start, report_period_end, checked_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            rows,
        )
        counts = {"Matched": 0, "Possible Match": 0, "Not Matched": 0}
        for r in results:
            counts[r.status.value] = counts.get(r.status.value, 0) + 1
        audit_matching.info(
            "Saved %d match results (Matched=%d, Possible=%d, NotMatched=%d)",
            len(results),
            counts["Matched"],
            counts["Possible Match"],
            counts["Not Matched"],
        )

    def list_by_period(self, start: date, end: date) -> list[MatchResult]:
        rows = self.db.query_all(
            "SELECT * FROM match_results WHERE report_period_start = ? AND report_period_end = ? "
            "ORDER BY confidence_score DESC",
            (start.isoformat(), end.isoformat()),
        )
        return [_row_to_model(row) for row in rows]

    def list_all(self, status: Optional[MatchStatus] = None) -> list[MatchResult]:
        if status:
            rows = self.db.query_all(
                "SELECT * FROM match_results WHERE status = ? ORDER BY checked_at DESC", (status.value,)
            )
        else:
            rows = self.db.query_all("SELECT * FROM match_results ORDER BY checked_at DESC")
        return [_row_to_model(row) for row in rows]

    def counts_summary(self) -> dict[str, int]:
        rows = self.db.query_all("SELECT status, COUNT(*) AS c FROM match_results GROUP BY status")
        return {row["status"]: row["c"] for row in rows}


def _row_to_model(row) -> MatchResult:
    return MatchResult(
        id=row["id"],
        recall_source=RecallSource(row["recall_source"]),
        recall_id=row["recall_id"],
        recall_number=row["recall_number"],
        inventory_id=row["inventory_id"],
        hospital_asset_number=row["hospital_asset_number"] or "",
        manufacturer=row["manufacturer"] or "",
        model=row["model"] or "",
        confidence_score=row["confidence_score"],
        status=MatchStatus(row["status"]),
        method=MatchMethod(row["method"]),
        reason=row["reason"] or "",
        report_period_start=date.fromisoformat(row["report_period_start"])
        if row["report_period_start"]
        else None,
        report_period_end=date.fromisoformat(row["report_period_end"]) if row["report_period_end"] else None,
        checked_at=datetime.fromisoformat(row["checked_at"]),
    )
