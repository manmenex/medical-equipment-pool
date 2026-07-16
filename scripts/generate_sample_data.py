"""
Generates the sample/demo assets shipped in `resources/`:

    resources/sample_inventory.xlsx   - example hospital inventory workbook
                                        (deliberately uses varied column
                                        header names to demonstrate the
                                        automatic column-mapping feature)
    resources/sample.db               - a small pre-populated SQLite database
                                        (FDA recalls, ECRI alerts, inventory,
                                        match results) so the app has
                                        something to show immediately
    resources/example_reports/        - one example Excel + PDF weekly report
                                        generated from the sample data

Run with:  python scripts/generate_sample_data.py
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from openpyxl import Workbook  # noqa: E402

from app.database.db import Database  # noqa: E402
from app.models.enums import MatchMethod, MatchStatus, RecallSource  # noqa: E402
from app.models.inventory import InventoryItem  # noqa: E402
from app.models.match import MatchResult  # noqa: E402
from app.models.recall import ECRIAlert, FDARecall  # noqa: E402
from app.models.report_data import ReportData  # noqa: E402
from app.reports.excel_report import generate_excel_report  # noqa: E402
from app.reports.pdf_report import generate_pdf_report  # noqa: E402
from app.services.fda_service import FDAService  # noqa: E402
from app.services.ecri_service import ECRIService  # noqa: E402
from app.services.inventory_service import InventoryService  # noqa: E402
from app.services.match_repository import MatchRepository  # noqa: E402
from app.services.period_service import get_period  # noqa: E402

RESOURCES_DIR = REPO_ROOT / "resources"


def generate_sample_inventory_xlsx(path: Path) -> None:
    """Write a demo hospital inventory workbook with intentionally varied
    column names, so the Excel importer's auto-mapping can be exercised.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Inventory"
    # Header row deliberately mixes exact + "close enough" synonyms.
    ws.append(
        [
            "Asset Number", "Equipment Code", "Device Name", "Mfr.", "Brand", "Model",
            "Catalog No", "UDI", "Serial No", "Department", "Room", "Purchase Date", "Status",
        ]
    )
    rows = [
        ["A-1001", "EQ-INF", "Infusion Pump", "Acme Medical", "PumpMaster", "IP-3000", "CAT-3000",
         "(01)00844588003288", "SN-100234", "ICU", "ICU-Room-4", "2021-03-15", "In Service"],
        ["A-1002", "EQ-VENT", "Ventilator", "Zenith Health", "AeroFlow", "VT-750", "CAT-750",
         "(01)00844588003295", "SN-100235", "ICU", "ICU-Room-2", "2020-11-02", "In Service"],
        ["A-1003", "EQ-MON", "Patient Monitor", "Acme Medical", "VitalView", "PM-500", "CAT-500",
         "(01)00844588003301", "SN-100236", "ER", "ER-Bay-1", "2019-07-22", "In Service"],
        ["A-1004", "EQ-DEF", "Defibrillator", "Zenith Health", "ShockWave", "DF-200", "CAT-200",
         "(01)00844588003318", "SN-100237", "ER", "ER-Bay-3", "2022-01-09", "In Service"],
        ["A-1005", "EQ-INF2", "Infusion Pump", "Acme Medical", "PumpMaster", "IP-3000", "CAT-3000",
         "(01)00844588003325", "SN-100238", "Oncology", "Onc-Room-1", "2021-05-30", "In Service"],
        ["A-1006", "EQ-BED", "Hospital Bed", "Comfort Beds Inc", "RestEase", "HB-100", "CAT-100",
         "", "SN-100239", "General Ward", "GW-Room-12", "2018-02-14", "In Service"],
        ["A-1007", "EQ-US", "Ultrasound Machine", "Zenith Health", "ClearScan", "US-900", "CAT-900",
         "(01)00844588003332", "SN-100240", "Radiology", "Rad-Room-2", "2020-08-18", "In Service"],
        ["A-1008", "EQ-PUMP3", "Syringe Pump", "Acme Medical", "PumpMaster", "SP-100", "CAT-1100",
         "(01)00844588003349", "SN-100241", "Pediatrics", "Peds-Room-3", "2023-02-01", "In Service"],
    ]
    for row in rows:
        ws.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    print(f"Wrote {path}")


def _seed_database(db: Database) -> None:
    fda = FDAService(db, scraper=None)  # scraper unused for seeding
    ecri = ECRIService(db, scraper=None, credential_service=None)  # unused for seeding
    inventory = InventoryService(db)
    repo = MatchRepository(db)

    period = get_period(2026, 7, 2)  # July 2026, Week 2 (day 8-14)

    fda_recalls = [
        FDARecall(
            recall_number="Z-1234-2026",
            recall_class="Class I",
            product="Infusion Pump IP-3000",
            manufacturer="Acme Medical",
            reason="Pump may stop infusion without alarming.",
            date_initiated=date(2026, 7, 9),
            status="Ongoing",
            distribution="Nationwide",
            quantity="1,204 units",
            model_number="IP-3000",
            catalog_number="CAT-3000",
            udi="(01)00844588003288",
            recall_url="https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfres/res.cfm?id=Z-1234-2026",
        ),
        FDARecall(
            recall_number="Z-1235-2026",
            recall_class="Class II",
            product="Ventilator VT-750",
            manufacturer="Zenith Health",
            reason="Battery indicator may show incorrect charge level.",
            date_initiated=date(2026, 7, 11),
            status="Ongoing",
            distribution="Nationwide",
            quantity="856 units",
            model_number="VT-750",
            catalog_number="CAT-750",
            udi="(01)00844588003295",
            recall_url="https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfres/res.cfm?id=Z-1235-2026",
        ),
    ]
    for r in fda_recalls:
        fda._insert(r)

    ecri_alerts = [
        ECRIAlert(
            alert_number="ECRI-8891",
            title="Ultrasound Machine US-900 probe connector failure risk",
            manufacturer="Zenith Health",
            product="Ultrasound Machine",
            model_number="US-900",
            hazard_level="High",
            date_issued=date(2026, 7, 10),
            status="Active",
            summary="Reports of probe connector overheating during extended use.",
            alert_url="https://sts.ecri.org/alerts/ECRI-8891",
        ),
    ]
    for a in ecri_alerts:
        ecri._insert(a)

    inventory.import_excel(RESOURCES_DIR / "sample_inventory.xlsx")
    all_inventory = inventory.list_all()

    from app.services.matching_service import MatchingService

    matcher = MatchingService(matched_threshold=90, possible_threshold=75)
    all_fda = fda.list_all()
    all_ecri = ecri.list_all()
    results = matcher.match_all(all_fda, all_ecri, all_inventory, (period.start_date, period.end_date))
    repo.save_all(results)

    db.execute(
        "INSERT OR REPLACE INTO app_settings (key, value, updated_at) VALUES (?,?,?)",
        ("last_update", datetime.now().isoformat(), datetime.now().isoformat()),
    )

    return period, all_fda, all_ecri, results


def generate_sample_database(path: Path) -> tuple:
    if path.exists():
        path.unlink()
    db = Database(path)
    result = _seed_database(db)
    db.close()
    print(f"Wrote {path}")
    return result


def generate_example_reports(period, fda_recalls, ecri_alerts, match_results, out_dir: Path) -> None:
    data = ReportData(period=period, fda_recalls=fda_recalls, ecri_alerts=ecri_alerts, match_results=match_results)
    out_dir.mkdir(parents=True, exist_ok=True)
    base_name = f"Recall_Report_{period.label}"
    generate_excel_report(data, out_dir / f"{base_name}.xlsx")
    generate_pdf_report(data, out_dir / f"{base_name}.pdf")
    print(f"Wrote example reports to {out_dir}")


def main() -> None:
    inventory_path = RESOURCES_DIR / "sample_inventory.xlsx"
    generate_sample_inventory_xlsx(inventory_path)

    db_path = RESOURCES_DIR / "sample.db"
    period, fda_recalls, ecri_alerts, match_results = generate_sample_database(db_path)

    generate_example_reports(period, fda_recalls, ecri_alerts, match_results, RESOURCES_DIR / "example_reports")


if __name__ == "__main__":
    main()
