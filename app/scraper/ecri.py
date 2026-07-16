"""
ECRI Alerts Tracker scraper (FUNCTION 2).

sts.ecri.org is a subscription-only portal. Because this module was
developed without an authorized ECRI account (and this sandbox's network
policy also blocks the host outright), the exact page markup cannot be
verified here. The scraper is therefore written *generically*:

    - Login: locates the username/password inputs and submit button using
      several label/placeholder/name-based fallback strategies (see
      `_LoginSelectors`), rather than one hardcoded ID.
    - Alert listing: rather than assuming fixed column names, it reads
      whatever header row is present on the results table/list and keeps
      every column, mapping well-known ones (title, manufacturer, model,
      alert/catalog number, hazard level, date, status) onto `ECRIAlert`
      fields via `_FIELD_ALIASES` and preserving the rest in `raw_data`
      (JSON) - satisfying "collect every available field" without
      hardcoding an incomplete/wrong schema.

Session handling: Playwright's `storage_state` (cookies) is cached in
memory for the scraper's lifetime. If a request unexpectedly lands back
on the login page (session expired mid-run), `SessionExpiredError` is
raised and the calling service (`ECRIService`) transparently logs back in
and retries the fetch exactly once.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from app.models.recall import ECRIAlert
from app.scraper.base import ScraperSession, translate_playwright_errors
from app.utils.exceptions import LoginFailedError, SessionExpiredError, WebsiteStructureChangedError
from app.utils.logging_config import get_audit_logger, get_logger

logger = get_logger(__name__)
audit_login = get_audit_logger("login")
audit_download = get_audit_logger("download")

MAX_PAGES = 50


class _LoginSelectors:
    @staticmethod
    def username_input(page):
        return [
            lambda: page.get_by_label("Username", exact=False),
            lambda: page.get_by_label("Email", exact=False),
            lambda: page.get_by_placeholder("Username", exact=False),
            lambda: page.get_by_placeholder("Email", exact=False),
            lambda: page.locator("input[name='username']"),
            lambda: page.locator("input[name='email']"),
            lambda: page.locator("input[type='email']"),
        ]

    @staticmethod
    def password_input(page):
        return [
            lambda: page.get_by_label("Password", exact=False),
            lambda: page.locator("input[type='password']"),
            lambda: page.locator("input[name='password']"),
        ]

    @staticmethod
    def submit_button(page):
        return [
            lambda: page.get_by_role("button", name="Log In", exact=False),
            lambda: page.get_by_role("button", name="Sign In", exact=False),
            lambda: page.get_by_role("button", name="Login", exact=False),
            lambda: page.locator("button[type='submit']"),
            lambda: page.locator("input[type='submit']"),
        ]

    @staticmethod
    def login_error(page):
        return [
            lambda: page.get_by_text("invalid", exact=False),
            lambda: page.get_by_text("incorrect", exact=False),
            lambda: page.get_by_text("failed", exact=False),
        ]


class _ListingSelectors:
    @staticmethod
    def results_container(page):
        return [
            lambda: page.locator("table.alerts-table"),
            lambda: page.locator("table").filter(has_text="Alert"),
            lambda: page.locator("[data-testid='alerts-list']"),
            lambda: page.locator("table"),
        ]

    @staticmethod
    def next_page_link(page):
        return [
            lambda: page.get_by_role("link", name="Next", exact=False),
            lambda: page.locator("a.next-page"),
            lambda: page.get_by_role("button", name="Next", exact=False),
        ]


def _first_visible(candidates, timeout_ms: int = 4000):
    for make_locator in candidates:
        try:
            locator = make_locator()
            locator.first.wait_for(state="visible", timeout=timeout_ms)
            return locator.first
        except Exception:
            continue
    return None


_FIELD_ALIASES: dict[str, str] = {
    "alertnumber": "alert_number",
    "id": "alert_number",
    "referenceid": "alert_number",
    "title": "title",
    "alerttitle": "title",
    "manufacturer": "manufacturer",
    "product": "product",
    "device": "product",
    "productname": "product",
    "model": "model_number",
    "modelnumber": "model_number",
    "catalognumber": "catalog_number",
    "catalogno": "catalog_number",
    "hazardlevel": "hazard_level",
    "priority": "hazard_level",
    "type": "alert_type",
    "alerttype": "alert_type",
    "dateissued": "date_issued",
    "date": "date_issued",
    "published": "date_issued",
    "status": "status",
    "summary": "summary",
    "description": "summary",
}


def _normalize_header(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _parse_date(text: str) -> Optional[date]:
    text = (text or "").strip()
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _row_to_alert(row: dict[str, str]) -> Optional[ECRIAlert]:
    mapped: dict[str, Any] = {}
    for header, value in row.items():
        key = _FIELD_ALIASES.get(_normalize_header(header))
        if key:
            mapped[key] = value

    alert_number = mapped.get("alert_number") or row.get("__detail_url__", "")
    if not alert_number:
        # Fall back to a stable synthetic key so we never silently drop a row.
        alert_number = f"{mapped.get('title', '')[:40]}::{mapped.get('date_issued', '')}"
    if not alert_number.strip():
        return None

    return ECRIAlert(
        alert_number=alert_number.strip(),
        title=mapped.get("title", ""),
        manufacturer=mapped.get("manufacturer", ""),
        product=mapped.get("product", ""),
        model_number=mapped.get("model_number", ""),
        catalog_number=mapped.get("catalog_number", ""),
        hazard_level=mapped.get("hazard_level", ""),
        alert_type=mapped.get("alert_type", ""),
        date_issued=_parse_date(mapped.get("date_issued", "")),
        status=mapped.get("status", ""),
        summary=mapped.get("summary", ""),
        alert_url=row.get("__detail_url__", ""),
        raw_data={k: v for k, v in row.items() if not k.startswith("__")},
    )


@dataclass
class _Session:
    session: ScraperSession
    page: Any


class ECRIScraper:
    """Logs into ECRI STS and scrapes the Alerts Tracker listing."""

    def __init__(
        self,
        login_url: str,
        alerts_url: str,
        headless: bool = True,
        browser_name: str = "chromium",
        timeout_ms: int = 30000,
    ):
        self.login_url = login_url
        self.alerts_url = alerts_url
        self.headless = headless
        self.browser_name = browser_name
        self.timeout_ms = timeout_ms

    def fetch_alerts(
        self, username: str, password: str, start_date: date, end_date: date
    ) -> list[ECRIAlert]:
        """Log in and scrape all alerts, re-authenticating once if the session drops."""
        with translate_playwright_errors("ECRI Alerts Tracker"):
            with ScraperSession(
                headless=self.headless,
                browser_name=self.browser_name,
                default_timeout_ms=self.timeout_ms,
            ) as session:
                page = session.new_page()
                self._login(page, username, password)
                try:
                    alerts = self._scrape_alerts(page, start_date, end_date)
                except SessionExpiredError:
                    logger.info("ECRI session expired mid-scrape; re-authenticating once.")
                    self._login(page, username, password)
                    alerts = self._scrape_alerts(page, start_date, end_date)

        audit_download.info(
            "ECRI scrape succeeded: %d alerts for %s..%s", len(alerts), start_date, end_date
        )
        return alerts

    # -- login -----------------------------------------------------------------
    def _login(self, page, username: str, password: str) -> None:
        page.goto(self.login_url, wait_until="domcontentloaded")

        username_input = _first_visible(_LoginSelectors.username_input(page))
        password_input = _first_visible(_LoginSelectors.password_input(page))
        submit_button = _first_visible(_LoginSelectors.submit_button(page))

        if not (username_input and password_input and submit_button):
            raise WebsiteStructureChangedError(
                "Could not locate ECRI's login form fields. The portal's layout may have changed."
            )

        username_input.fill(username)
        password_input.fill(password)
        submit_button.click()
        page.wait_for_load_state("domcontentloaded")

        error_locator = _first_visible(_LoginSelectors.login_error(page), timeout_ms=2000)
        if error_locator is not None:
            audit_login.warning("ECRI login failed for user=%s", username)
            raise LoginFailedError(
                "ECRI login failed - the portal reported an error. "
                "Check the username/password saved in Settings."
            )

        # If we're still sitting on a page with a password field, login silently
        # did not succeed (e.g. wrong credentials with no visible error banner).
        still_on_login = _first_visible(_LoginSelectors.password_input(page), timeout_ms=1500)
        if still_on_login is not None:
            audit_login.warning("ECRI login did not progress past the login form for user=%s", username)
            raise LoginFailedError("ECRI login failed - please verify your credentials.")

        audit_login.info("ECRI login succeeded for user=%s", username)

    # -- scraping ----------------------------------------------------------------
    def _scrape_alerts(self, page, start_date: date, end_date: date) -> list[ECRIAlert]:
        page.goto(self.alerts_url, wait_until="domcontentloaded")

        if _first_visible(_LoginSelectors.password_input(page), timeout_ms=1500) is not None:
            raise SessionExpiredError("ECRI session expired - redirected back to the login page.")

        all_alerts: list[ECRIAlert] = []
        for _ in range(MAX_PAGES):
            table = _first_visible(_ListingSelectors.results_container(page), timeout_ms=8000)
            if table is None:
                raise WebsiteStructureChangedError(
                    "Could not locate the ECRI alerts listing. The portal's layout may have changed."
                )
            rows = self._parse_table(table)
            for row in rows:
                alert = _row_to_alert(row)
                if alert:
                    all_alerts.append(alert)

            next_link = _first_visible(_ListingSelectors.next_page_link(page), timeout_ms=2000)
            if next_link is None:
                break
            next_link.click()
            page.wait_for_load_state("domcontentloaded")

        in_range = [
            a
            for a in all_alerts
            if a.date_issued is None or (start_date <= a.date_issued <= end_date)
        ]
        return _dedupe(in_range)

    @staticmethod
    def _parse_table(table) -> list[dict[str, str]]:
        headers = [h.strip() for h in table.locator("thead th").all_inner_texts()]
        if not headers:
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


def _dedupe(alerts: list[ECRIAlert]) -> list[ECRIAlert]:
    seen: dict[str, ECRIAlert] = {}
    for alert in alerts:
        seen[alert.natural_key()] = alert
    return list(seen.values())
