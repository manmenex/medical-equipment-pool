"""Service layer orchestrating the FDA scraper + persistence (FUNCTION 1)."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Optional

from app.database.db import Database
from app.models.recall import FDARecall
from app.scraper.fda import FDAScraper
from app.utils.exceptions import DuplicateRecallError
from app.utils.logging_config import get_audit_logger, get_logger

logger = get_logger(__name__)
audit_import = get_audit_logger("import")


def _to_iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def _from_iso(s: Optional[str]) -> Optional[date]:
    return date.fromisoformat(s) if s else None


class FDAService:
    def __init__(self, db: Database, scraper: FDAScraper):
        self.db = db
        self.scraper = scraper

    def refresh(self, start_date: date, end_date: date) -> tuple[int, int]:
        """Fetch recalls for the date range and upsert them into SQLite.

        Returns (new_count, updated_count).
        """
        recalls = self.scraper.fetch_recalls(start_date, end_date)
        new_count = 0
        updated_count = 0
        for recall in recalls:
            existing = self.db.query_one(
                "SELECT id FROM fda_recalls WHERE recall_number = ?", (recall.recall_number,)
            )
            if existing:
                self._update(recall, existing["id"])
                updated_count += 1
            else:
                self._insert(recall)
                new_count += 1
        audit_import.info(
            "FDA refresh %s..%s: %d new, %d updated (of %d fetched)",
            start_date,
            end_date,
            new_count,
            updated_count,
            len(recalls),
        )
        return new_count, updated_count

    def _insert(self, recall: FDARecall) -> int:
        cur = self.db.execute(
            """
            INSERT INTO fda_recalls (
                recall_number, recall_class, product, product_code, manufacturer, reason,
                date_initiated, date_posted, date_terminated, status, distribution, quantity,
                model_number, catalog_number, udi, k_numbers, event_id, recall_url,
                root_cause, action_taken, raw_data, fetched_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                recall.recall_number,
                recall.recall_class,
                recall.product,
                recall.product_code,
                recall.manufacturer,
                recall.reason,
                _to_iso(recall.date_initiated),
                _to_iso(recall.date_posted),
                _to_iso(recall.date_terminated),
                recall.status,
                recall.distribution,
                recall.quantity,
                recall.model_number,
                recall.catalog_number,
                recall.udi,
                recall.k_numbers,
                recall.event_id,
                recall.recall_url,
                recall.root_cause,
                recall.action_taken,
                json.dumps(recall.raw_data, default=str),
                recall.fetched_at.isoformat(),
            ),
        )
        return cur.lastrowid

    def _update(self, recall: FDARecall, existing_id: int) -> None:
        self.db.execute(
            """
            UPDATE fda_recalls SET
                recall_class=?, product=?, product_code=?, manufacturer=?, reason=?,
                date_initiated=?, date_posted=?, date_terminated=?, status=?, distribution=?,
                quantity=?, model_number=?, catalog_number=?, udi=?, k_numbers=?, event_id=?,
                recall_url=?, root_cause=?, action_taken=?, raw_data=?, fetched_at=?
            WHERE id=?
            """,
            (
                recall.recall_class,
                recall.product,
                recall.product_code,
                recall.manufacturer,
                recall.reason,
                _to_iso(recall.date_initiated),
                _to_iso(recall.date_posted),
                _to_iso(recall.date_terminated),
                recall.status,
                recall.distribution,
                recall.quantity,
                recall.model_number,
                recall.catalog_number,
                recall.udi,
                recall.k_numbers,
                recall.event_id,
                recall.recall_url,
                recall.root_cause,
                recall.action_taken,
                json.dumps(recall.raw_data, default=str),
                recall.fetched_at.isoformat(),
                existing_id,
            ),
        )

    def list_all(self) -> list[FDARecall]:
        rows = self.db.query_all("SELECT * FROM fda_recalls ORDER BY date_initiated DESC")
        return [_row_to_model(row) for row in rows]

    def list_between(self, start_date: date, end_date: date) -> list[FDARecall]:
        rows = self.db.query_all(
            "SELECT * FROM fda_recalls WHERE date_initiated BETWEEN ? AND ? ORDER BY date_initiated DESC",
            (start_date.isoformat(), end_date.isoformat()),
        )
        return [_row_to_model(row) for row in rows]

    def count(self) -> int:
        row = self.db.query_one("SELECT COUNT(*) AS c FROM fda_recalls")
        return int(row["c"]) if row else 0


def _row_to_model(row) -> FDARecall:
    return FDARecall(
        id=row["id"],
        recall_number=row["recall_number"],
        recall_class=row["recall_class"] or "",
        product=row["product"] or "",
        product_code=row["product_code"] or "",
        manufacturer=row["manufacturer"] or "",
        reason=row["reason"] or "",
        date_initiated=_from_iso(row["date_initiated"]),
        date_posted=_from_iso(row["date_posted"]),
        date_terminated=_from_iso(row["date_terminated"]),
        status=row["status"] or "",
        distribution=row["distribution"] or "",
        quantity=row["quantity"] or "",
        model_number=row["model_number"] or "",
        catalog_number=row["catalog_number"] or "",
        udi=row["udi"] or "",
        k_numbers=row["k_numbers"] or "",
        event_id=row["event_id"] or "",
        recall_url=row["recall_url"] or "",
        root_cause=row["root_cause"] or "",
        action_taken=row["action_taken"] or "",
        raw_data=json.loads(row["raw_data"]) if row["raw_data"] else {},
        fetched_at=datetime.fromisoformat(row["fetched_at"]),
    )
