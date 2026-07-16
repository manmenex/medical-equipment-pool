"""Service layer orchestrating the ECRI scraper, credentials and persistence."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Optional

from app.database.db import Database
from app.models.recall import ECRIAlert
from app.scraper.ecri import ECRIScraper
from app.services.credential_service import CredentialService
from app.utils.exceptions import CredentialError
from app.utils.logging_config import get_audit_logger, get_logger

logger = get_logger(__name__)
audit_import = get_audit_logger("import")

ECRI_SERVICE_NAME = "ECRI"


def _from_iso(s: Optional[str]) -> Optional[date]:
    return date.fromisoformat(s) if s else None


class ECRIService:
    def __init__(self, db: Database, scraper: ECRIScraper, credential_service: CredentialService):
        self.db = db
        self.scraper = scraper
        self.credential_service = credential_service

    def has_credentials(self) -> bool:
        return self.credential_service.has_credentials(ECRI_SERVICE_NAME)

    def refresh(self, start_date: date, end_date: date) -> tuple[int, int]:
        creds = self.credential_service.get_credentials(ECRI_SERVICE_NAME)
        if not creds:
            raise CredentialError(
                "No ECRI credentials are stored yet. Please log in from the ECRI page first."
            )
        username, password = creds
        alerts = self.scraper.fetch_alerts(username, password, start_date, end_date)

        new_count = 0
        updated_count = 0
        for alert in alerts:
            existing = self.db.query_one(
                "SELECT id FROM ecri_alerts WHERE alert_number = ?", (alert.alert_number,)
            )
            if existing:
                self._update(alert, existing["id"])
                updated_count += 1
            else:
                self._insert(alert)
                new_count += 1

        audit_import.info(
            "ECRI refresh %s..%s: %d new, %d updated (of %d fetched)",
            start_date,
            end_date,
            new_count,
            updated_count,
            len(alerts),
        )
        return new_count, updated_count

    def _insert(self, alert: ECRIAlert) -> int:
        cur = self.db.execute(
            """
            INSERT INTO ecri_alerts (
                alert_number, title, manufacturer, product, model_number, catalog_number,
                hazard_level, alert_type, date_issued, status, summary, alert_url,
                raw_data, fetched_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                alert.alert_number,
                alert.title,
                alert.manufacturer,
                alert.product,
                alert.model_number,
                alert.catalog_number,
                alert.hazard_level,
                alert.alert_type,
                alert.date_issued.isoformat() if alert.date_issued else None,
                alert.status,
                alert.summary,
                alert.alert_url,
                json.dumps(alert.raw_data, default=str),
                alert.fetched_at.isoformat(),
            ),
        )
        return cur.lastrowid

    def _update(self, alert: ECRIAlert, existing_id: int) -> None:
        self.db.execute(
            """
            UPDATE ecri_alerts SET
                title=?, manufacturer=?, product=?, model_number=?, catalog_number=?,
                hazard_level=?, alert_type=?, date_issued=?, status=?, summary=?,
                alert_url=?, raw_data=?, fetched_at=?
            WHERE id=?
            """,
            (
                alert.title,
                alert.manufacturer,
                alert.product,
                alert.model_number,
                alert.catalog_number,
                alert.hazard_level,
                alert.alert_type,
                alert.date_issued.isoformat() if alert.date_issued else None,
                alert.status,
                alert.summary,
                alert.alert_url,
                json.dumps(alert.raw_data, default=str),
                alert.fetched_at.isoformat(),
                existing_id,
            ),
        )

    def list_all(self) -> list[ECRIAlert]:
        rows = self.db.query_all("SELECT * FROM ecri_alerts ORDER BY date_issued DESC")
        return [_row_to_model(row) for row in rows]

    def list_between(self, start_date: date, end_date: date) -> list[ECRIAlert]:
        rows = self.db.query_all(
            "SELECT * FROM ecri_alerts WHERE date_issued BETWEEN ? AND ? ORDER BY date_issued DESC",
            (start_date.isoformat(), end_date.isoformat()),
        )
        return [_row_to_model(row) for row in rows]

    def count(self) -> int:
        row = self.db.query_one("SELECT COUNT(*) AS c FROM ecri_alerts")
        return int(row["c"]) if row else 0


def _row_to_model(row) -> ECRIAlert:
    return ECRIAlert(
        id=row["id"],
        alert_number=row["alert_number"],
        title=row["title"] or "",
        manufacturer=row["manufacturer"] or "",
        product=row["product"] or "",
        model_number=row["model_number"] or "",
        catalog_number=row["catalog_number"] or "",
        hazard_level=row["hazard_level"] or "",
        alert_type=row["alert_type"] or "",
        date_issued=_from_iso(row["date_issued"]),
        status=row["status"] or "",
        summary=row["summary"] or "",
        alert_url=row["alert_url"] or "",
        raw_data=json.loads(row["raw_data"]) if row["raw_data"] else {},
        fetched_at=datetime.fromisoformat(row["fetched_at"]),
    )
