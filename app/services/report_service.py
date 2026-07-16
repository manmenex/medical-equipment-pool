"""
Report orchestration service (FUNCTIONS 5 & 6).

Ties together: period calculation -> FDA/ECRI data for that period ->
matching engine -> Excel/PDF rendering -> `report_runs` audit row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.database.db import Database
from app.models.period import ReportPeriod
from app.models.report_data import ReportData
from app.reports.excel_report import generate_excel_report
from app.reports.pdf_report import generate_pdf_report
from app.services.ecri_service import ECRIService
from app.services.fda_service import FDAService
from app.services.inventory_service import InventoryService
from app.services.match_repository import MatchRepository
from app.services.matching_service import MatchingService
from app.services.period_service import get_period
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class ReportFilters:
    manufacturer: Optional[str] = None
    department: Optional[str] = None
    recall_class: Optional[str] = None


def _apply_filters(data: ReportData, filters: ReportFilters, inventory_by_asset: dict) -> ReportData:
    fda = data.fda_recalls
    ecri = data.ecri_alerts
    matches = data.match_results

    if filters.manufacturer:
        needle = filters.manufacturer.lower()
        fda = [r for r in fda if needle in (r.manufacturer or "").lower()]
        ecri = [a for a in ecri if needle in (a.manufacturer or "").lower()]
        matches = [m for m in matches if needle in (m.manufacturer or "").lower()]

    if filters.recall_class:
        fda = [r for r in fda if r.recall_class == filters.recall_class]

    if filters.department:
        matched_assets = {
            asset
            for asset, item in inventory_by_asset.items()
            if item.department == filters.department
        }
        matches = [m for m in matches if m.hospital_asset_number in matched_assets]

    return ReportData(period=data.period, fda_recalls=fda, ecri_alerts=ecri, match_results=matches)


class ReportService:
    def __init__(
        self,
        db: Database,
        fda_service: FDAService,
        ecri_service: ECRIService,
        inventory_service: InventoryService,
        matching_service: MatchingService,
        output_dir: Path,
    ):
        self.db = db
        self.fda_service = fda_service
        self.ecri_service = ecri_service
        self.inventory_service = inventory_service
        self.matching_service = matching_service
        self.match_repository = MatchRepository(db)
        self.output_dir = Path(output_dir)

    def build_report_data(
        self, period: ReportPeriod, run_matching: bool = True, filters: Optional[ReportFilters] = None
    ) -> ReportData:
        fda_recalls = self.fda_service.list_between(period.start_date, period.end_date)
        ecri_alerts = self.ecri_service.list_between(period.start_date, period.end_date)
        inventory_items = self.inventory_service.list_all()

        if run_matching:
            match_results = self.matching_service.match_all(
                fda_recalls, ecri_alerts, inventory_items, (period.start_date, period.end_date)
            )
            self.match_repository.save_all(match_results)
        else:
            match_results = self.match_repository.list_by_period(period.start_date, period.end_date)

        data = ReportData(
            period=period, fda_recalls=fda_recalls, ecri_alerts=ecri_alerts, match_results=match_results
        )

        if filters:
            inventory_by_asset = {i.asset_number: i for i in inventory_items}
            data = _apply_filters(data, filters, inventory_by_asset)

        return data

    def generate_weekly_report(
        self,
        year: int,
        month: int,
        week_number: int,
        formats: tuple[str, ...] = ("excel", "pdf"),
        filters: Optional[ReportFilters] = None,
    ) -> dict[str, Path]:
        """Run FDA/ECRI refresh is expected to have already happened; this
        method builds the report from whatever data is currently in SQLite
        for the requested period and renders it to disk.
        """
        period = get_period(year, month, week_number)
        data = self.build_report_data(period, run_matching=True, filters=filters)

        outputs: dict[str, Path] = {}
        base_name = f"Recall_Report_{period.label}"
        if "excel" in formats:
            outputs["excel"] = generate_excel_report(data, self.output_dir / f"{base_name}.xlsx")
        if "pdf" in formats:
            outputs["pdf"] = generate_pdf_report(data, self.output_dir / f"{base_name}.pdf")

        self._record_run(period, data, outputs)
        return outputs

    def _record_run(self, period: ReportPeriod, data: ReportData, outputs: dict[str, Path]) -> None:
        self.db.execute(
            """
            INSERT INTO report_runs (
                period_label, year, month, week_number, start_date, end_date,
                total_fda, total_ecri, total_matched, total_possible, total_not_matched,
                excel_path, pdf_path, generated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                period.label,
                period.year,
                period.month,
                period.week_number,
                period.start_date.isoformat(),
                period.end_date.isoformat(),
                data.total_fda,
                data.total_ecri,
                data.total_matched,
                data.total_possible,
                data.total_not_matched,
                str(outputs.get("excel", "")),
                str(outputs.get("pdf", "")),
                datetime.now().isoformat(),
            ),
        )

    def list_report_runs(self) -> list[dict]:
        rows = self.db.query_all("SELECT * FROM report_runs ORDER BY generated_at DESC")
        return [dict(row) for row in rows]
