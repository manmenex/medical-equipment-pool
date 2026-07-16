"""
FDA Medical Device Recall scraper (FUNCTION 1).

Primary path
------------
Playwright automation of the public search form at:
    https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfres/res.cfm

The form is driven using resilient, text/label-based Playwright locators
(rather than brittle auto-generated element IDs) so minor markup changes
don't immediately break the scraper. All selector strategies live in
`_SelectorStrategies` below in one place, ranked from most- to
least-specific, so if FDA changes the page only this section needs
updating.

NOTE ON SELECTOR VERIFICATION
------------------------------
This module was developed in a sandboxed environment whose network policy
blocks direct access to accessdata.fda.gov, so the exact selector
strategies below could not be interactively verified against the live
DOM. They are written defensively (multiple fallback strategies + a clear
`WebsiteStructureChangedError` if all of them fail) and should be smoke
tested against the live site before the first production run; adjust the
`_SelectorStrategies` lists if FDA's markup differs.

Resilient fallback path
------------------------
If the HTML scrape fails because the page layout has changed
(`WebsiteStructureChangedError`) and `FDA_USE_OPENFDA_FALLBACK=true`, the
scraper automatically retries using the public openFDA REST API
(`GET https://api.fda.gov/device/recall.json`), which is a stable,
documented, versioned JSON API published by the FDA covering the same
underlying recall data. This keeps weekly checks running even if the
res.cfm HTML page is redesigned, and is surfaced to the user as a
"used fallback data source" notice rather than a silent difference.
"""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import date, datetime
from typing import Any, Optional

import requests

from app.models.recall import FDARecall
from app.scraper.base import ScraperSession, translate_playwright_errors
from app.utils.exceptions import WebsiteStructureChangedError
from app.utils.logging_config import get_audit_logger, get_logger

logger = get_logger(__name__)
audit_download = get_audit_logger("download")

MAX_PAGES = 50
DATE_FORMATS_TO_TRY = ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y")


class _SelectorStrategies:
    """Ranked, fallback-friendly locator strategies for the res.cfm form.

    Each entry is a callable taking a Playwright `Page` and returning a
    `Locator`, tried in order until one resolves to a visible element.
    """

    @staticmethod
    def start_date_input(page):
        candidates = [
            lambda: page.get_by_label("Date Initiated (Start)", exact=False),
            lambda: page.locator("input[name='startdatetext']"),
            lambda: page.locator("input[name='start_date']"),
            lambda: page.locator("#startdatetext"),
        ]
        return candidates

    @staticmethod
    def end_date_input(page):
        candidates = [
            lambda: page.get_by_label("Date Initiated (End)", exact=False),
            lambda: page.locator("input[name='enddatetotext']"),
            lambda: page.locator("input[name='end_date']"),
            lambda: page.locator("#enddatetotext"),
        ]
        return candidates

    @staticmethod
    def submit_button(page):
        candidates = [
            lambda: page.get_by_role("button", name="Search", exact=False),
            lambda: page.get_by_role("button", name="Submit", exact=False),
            lambda: page.locator("input[type='submit']"),
            lambda: page.locator("button[type='submit']"),
        ]
        return candidates

    @staticmethod
    def results_table(page):
        candidates = [
            lambda: page.locator("table#results"),
            lambda: page.locator("table.recalls-table"),
            lambda: page.locator("table").filter(has_text="Recall Number"),
        ]
        return candidates

    @staticmethod
    def next_page_link(page):
        candidates = [
            lambda: page.get_by_role("link", name="Next", exact=False),
            lambda: page.locator("a.next-page"),
        ]
        return candidates


def _first_visible(candidates, timeout_ms: int = 4000):
    """Return the first candidate locator that resolves to a visible element."""
    for make_locator in candidates:
        try:
            locator = make_locator()
            locator.first.wait_for(state="visible", timeout=timeout_ms)
            return locator.first
        except Exception:
            continue
    return None


def _parse_date_cell(text: str) -> Optional[date]:
    text = (text or "").strip()
    if not text:
        return None
    for fmt in DATE_FORMATS_TO_TRY:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


# Maps normalized (lowercased, non-alnum stripped) header text -> FDARecall field.
_FIELD_ALIASES: dict[str, str] = {
    "recallnumber": "recall_number",
    "recalleventid": "event_id",
    "eventid": "event_id",
    "recallclass": "recall_class",
    "productclassification": "recall_class",
    "product": "product",
    "productdescription": "product",
    "manufacturer": "manufacturer",
    "recallingfirm": "manufacturer",
    "firmname": "manufacturer",
    "reason": "reason",
    "reasonforrecall": "reason",
    "dateinitiated": "date_initiated",
    "recallinitiationdate": "date_initiated",
    "dateposted": "date_posted",
    "datetereminated": "date_terminated",
    "dateterminated": "date_terminated",
    "status": "status",
    "distribution": "distribution",
    "distributionpattern": "distribution",
    "quantity": "quantity",
    "productquantity": "quantity",
    "modelnumber": "model_number",
    "catalognumber": "catalog_number",
    "udi": "udi",
    "knumbers": "k_numbers",
    "productcode": "product_code",
    "rootcause": "root_cause",
    "actiontaken": "action_taken",
}


def _normalize_header(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _row_to_recall(row: dict[str, str], base_url: str) -> Optional[FDARecall]:
    mapped: dict[str, Any] = {}
    for header, value in row.items():
        key = _FIELD_ALIASES.get(_normalize_header(header))
        if key:
            mapped[key] = value

    recall_number = mapped.get("recall_number") or row.get("Recall Number") or ""
    if not recall_number:
        return None

    for date_field in ("date_initiated", "date_posted", "date_terminated"):
        if date_field in mapped:
            mapped[date_field] = _parse_date_cell(mapped[date_field])

    return FDARecall(
        recall_number=recall_number.strip(),
        recall_class=mapped.get("recall_class", ""),
        product=mapped.get("product", ""),
        product_code=mapped.get("product_code", ""),
        manufacturer=mapped.get("manufacturer", ""),
        reason=mapped.get("reason", ""),
        date_initiated=mapped.get("date_initiated"),
        date_posted=mapped.get("date_posted"),
        date_terminated=mapped.get("date_terminated"),
        status=mapped.get("status", ""),
        distribution=mapped.get("distribution", ""),
        quantity=mapped.get("quantity", ""),
        model_number=mapped.get("model_number", ""),
        catalog_number=mapped.get("catalog_number", ""),
        udi=mapped.get("udi", ""),
        k_numbers=mapped.get("k_numbers", ""),
        event_id=mapped.get("event_id", ""),
        recall_url=row.get("__detail_url__", base_url),
        root_cause=mapped.get("root_cause", ""),
        action_taken=mapped.get("action_taken", ""),
        raw_data={k: v for k, v in row.items() if not k.startswith("__")},
    )


class FDAScraper:
    """Fetches FDA medical device recalls within a date range."""

    def __init__(
        self,
        search_url: str,
        openfda_api_url: str,
        use_openfda_fallback: bool = True,
        headless: bool = True,
        browser_name: str = "chromium",
        timeout_ms: int = 30000,
    ):
        self.search_url = search_url
        self.openfda_api_url = openfda_api_url
        self.use_openfda_fallback = use_openfda_fallback
        self.headless = headless
        self.browser_name = browser_name
        self.timeout_ms = timeout_ms

    # -- public API ----------------------------------------------------------
    def fetch_recalls(self, start_date: date, end_date: date) -> list[FDARecall]:
        """Return every FDA recall with a "date initiated" in [start_date, end_date]."""
        logger.info("Fetching FDA recalls %s - %s", start_date, end_date)
        try:
            recalls = self._scrape_html_form(start_date, end_date)
            audit_download.info(
                "FDA scrape (HTML form) succeeded: %d records for %s..%s",
                len(recalls),
                start_date,
                end_date,
            )
            return recalls
        except WebsiteStructureChangedError as exc:
            logger.warning("FDA HTML scrape failed (%s).", exc)
            if not self.use_openfda_fallback:
                raise
            logger.info("Falling back to openFDA REST API for this date range.")
            recalls = self._fetch_via_openfda(start_date, end_date)
            audit_download.info(
                "FDA fetch via openFDA fallback succeeded: %d records for %s..%s",
                len(recalls),
                start_date,
                end_date,
            )
            return recalls

    # -- Playwright HTML scrape ------------------------------------------------
    def _scrape_html_form(self, start_date: date, end_date: date) -> list[FDARecall]:
        with translate_playwright_errors("FDA Recall Search (res.cfm)"):
            with ScraperSession(
                headless=self.headless,
                browser_name=self.browser_name,
                default_timeout_ms=self.timeout_ms,
            ) as session:
                page = session.new_page()
                page.goto(self.search_url, wait_until="domcontentloaded")

                start_input = _first_visible(_SelectorStrategies.start_date_input(page))
                end_input = _first_visible(_SelectorStrategies.end_date_input(page))
                submit_button = _first_visible(_SelectorStrategies.submit_button(page))
                if not (start_input and end_input and submit_button):
                    raise WebsiteStructureChangedError(
                        "Could not locate the FDA search form's date fields or submit "
                        "button. The page layout may have changed."
                    )

                start_input.fill(start_date.strftime("%m/%d/%Y"))
                end_input.fill(end_date.strftime("%m/%d/%Y"))
                submit_button.click()
                page.wait_for_load_state("domcontentloaded")

                all_recalls: list[FDARecall] = []
                for _ in range(MAX_PAGES):
                    table = _first_visible(_SelectorStrategies.results_table(page), timeout_ms=8000)
                    if table is None:
                        raise WebsiteStructureChangedError(
                            "Could not locate the FDA results table after searching."
                        )
                    rows = self._parse_table(table)
                    for row in rows:
                        recall = _row_to_recall(row, self.search_url)
                        if recall:
                            all_recalls.append(recall)

                    next_link = _first_visible(
                        _SelectorStrategies.next_page_link(page), timeout_ms=2000
                    )
                    if next_link is None:
                        break
                    next_link.click()
                    page.wait_for_load_state("domcontentloaded")

                return _dedupe(all_recalls)

    @staticmethod
    def _parse_table(table) -> list[dict[str, str]]:
        headers = [h.strip() for h in table.locator("thead th").all_inner_texts()]
        if not headers:
            # Some ColdFusion tables put headers in the first <tr> instead of <thead>.
            first_row_cells = table.locator("tr").first.locator("th, td")
            headers = [h.strip() for h in first_row_cells.all_inner_texts()]

        body_rows = table.locator("tbody tr")
        count = body_rows.count()
        results = []
        for i in range(count):
            cells = [c.strip() for c in body_rows.nth(i).locator("td").all_inner_texts()]
            if not cells:
                continue
            row = {headers[j] if j < len(headers) else f"col{j}": cells[j] for j in range(len(cells))}
            link = body_rows.nth(i).locator("a").first
            try:
                href = link.get_attribute("href")
                if href:
                    row["__detail_url__"] = href
            except Exception:
                pass
            results.append(row)
        return results

    # -- openFDA REST fallback ---------------------------------------------------
    def _fetch_via_openfda(self, start_date: date, end_date: date) -> list[FDARecall]:
        query = (
            f"event_date_initiated:[{start_date.strftime('%Y%m%d')}"
            f"+TO+{end_date.strftime('%Y%m%d')}]"
        )
        limit = 100
        skip = 0
        all_recalls: list[FDARecall] = []

        while True:
            params = {"search": query, "limit": limit, "skip": skip}
            try:
                response = requests.get(self.openfda_api_url, params=params, timeout=30)
            except requests.RequestException as exc:
                raise WebsiteStructureChangedError(f"openFDA API request failed: {exc}") from exc

            if response.status_code == 404:
                # openFDA returns 404 when a search matches zero records.
                break
            if not response.ok:
                raise WebsiteStructureChangedError(
                    f"openFDA API returned HTTP {response.status_code}: {response.text[:200]}"
                )

            payload = response.json()
            results = payload.get("results", [])
            for item in results:
                all_recalls.append(_openfda_item_to_recall(item))

            total = payload.get("meta", {}).get("results", {}).get("total", 0)
            skip += limit
            if skip >= total or not results:
                break
            time.sleep(0.25)  # be a polite API citizen

        return _dedupe(all_recalls)


def _openfda_item_to_recall(item: dict[str, Any]) -> FDARecall:
    def _date(value: str | None) -> Optional[date]:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y%m%d").date()
        except ValueError:
            return None

    openfda = item.get("openfda", {}) or {}
    return FDARecall(
        recall_number=item.get("product_res_number", "") or item.get("res_event_number", ""),
        recall_class=item.get("action_classification", ""),
        product=item.get("product_description", "") or ", ".join(openfda.get("device_name", []) or []),
        product_code=item.get("product_code", ""),
        manufacturer=item.get("recalling_firm", ""),
        reason=item.get("reason_for_recall", ""),
        date_initiated=_date(item.get("event_date_initiated")),
        date_posted=_date(item.get("event_date_created")),
        date_terminated=_date(item.get("event_date_terminated")),
        status=item.get("recall_status", ""),
        distribution=item.get("distribution_pattern", ""),
        quantity=item.get("product_quantity", ""),
        model_number="",
        catalog_number="",
        udi="",
        k_numbers=", ".join(item.get("k_numbers", []) or []),
        event_id=item.get("cfres_id", ""),
        recall_url="https://api.fda.gov/device/recall.json",
        root_cause=item.get("root_cause_description", ""),
        action_taken=item.get("firm_fda_action", ""),
        raw_data=item,
    )


def _dedupe(recalls: list[FDARecall]) -> list[FDARecall]:
    seen: dict[str, FDARecall] = {}
    for recall in recalls:
        seen[recall.natural_key()] = recall
    return list(seen.values())
