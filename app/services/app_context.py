"""
Composition root: wires config -> database -> scraper -> service objects
into one `AppContext` that the UI, scheduler and CLI/test code all share.

Keeping this in one place means there is exactly one spot that knows how
to construct a fully working `ReportService` (with its FDA/ECRI/inventory/
matching dependencies) - useful both for `main.py` and for the background
scheduler, which needs the same services without a GUI.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config.settings import Settings
from app.database.db import Database, get_database
from app.scraper.ecri import ECRIScraper
from app.scraper.fda import FDAScraper
from app.services.credential_service import CredentialService, get_credential_service
from app.services.ecri_service import ECRIService
from app.services.fda_service import FDAService
from app.services.inventory_service import InventoryService
from app.services.match_repository import MatchRepository
from app.services.matching_service import MatchingService
from app.services.report_service import ReportService


@dataclass
class AppContext:
    settings: Settings
    db: Database
    credential_service: CredentialService
    fda_service: FDAService
    ecri_service: ECRIService
    inventory_service: InventoryService
    matching_service: MatchingService
    match_repository: MatchRepository
    report_service: ReportService


def build_app_context(settings: Settings) -> AppContext:
    db = get_database(settings.database_path)
    credential_service = get_credential_service()

    fda_scraper = FDAScraper(
        search_url=settings.fda_search_url,
        openfda_api_url=settings.fda_openfda_api_url,
        use_openfda_fallback=settings.fda_use_openfda_fallback,
        headless=settings.playwright_headless,
        browser_name=settings.playwright_browser,
        timeout_ms=settings.fda_request_timeout_ms,
    )
    ecri_scraper = ECRIScraper(
        login_url=settings.ecri_login_url,
        alerts_url=settings.ecri_alerts_url,
        headless=settings.playwright_headless,
        browser_name=settings.playwright_browser,
        timeout_ms=settings.ecri_request_timeout_ms,
    )

    fda_service = FDAService(db, fda_scraper)
    ecri_service = ECRIService(db, ecri_scraper, credential_service)
    inventory_service = InventoryService(db)
    matching_service = MatchingService(
        matched_threshold=settings.fuzzy_match_threshold,
        possible_threshold=settings.possible_match_threshold,
    )
    report_service = ReportService(
        db=db,
        fda_service=fda_service,
        ecri_service=ecri_service,
        inventory_service=inventory_service,
        matching_service=matching_service,
        output_dir=settings.download_dir,
    )

    return AppContext(
        settings=settings,
        db=db,
        credential_service=credential_service,
        fda_service=fda_service,
        ecri_service=ecri_service,
        inventory_service=inventory_service,
        matching_service=matching_service,
        match_repository=report_service.match_repository,
        report_service=report_service,
    )
