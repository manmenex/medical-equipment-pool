"""
Shared Playwright plumbing used by both the FDA and ECRI scrapers.

Centralizing browser/context creation here means:
    - one place controls headless mode, timeouts and the download directory
    - one place turns raw Playwright exceptions into the app's own
      exception hierarchy (FUNCTION 12 - ERROR HANDLING), so callers in
      `services/` and the UI only need to handle `AppError` subclasses.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from app.utils.exceptions import (
    NetworkUnavailableError,
    WebsiteStructureChangedError,
    WebsiteTimeoutError,
)
from app.utils.logging_config import get_logger
from app.utils.validators import check_internet_connection

logger = get_logger(__name__)


class ScraperSession:
    """Owns a Playwright instance/browser/context for the duration of a scrape.

    Usage::

        with ScraperSession(headless=True, download_dir=Path("./downloads")) as session:
            page = session.new_page()
            page.goto("https://example.com")
    """

    def __init__(
        self,
        headless: bool = True,
        browser_name: str = "chromium",
        download_dir: Optional[Path] = None,
        default_timeout_ms: int = 30000,
    ):
        self.headless = headless
        self.browser_name = browser_name
        self.download_dir = download_dir
        self.default_timeout_ms = default_timeout_ms
        self._playwright = None
        self._browser = None
        self._context = None

    def __enter__(self) -> "ScraperSession":
        if not check_internet_connection():
            raise NetworkUnavailableError(
                "No internet connection detected - cannot reach external recall sources."
            )
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        browser_type = getattr(self._playwright, self.browser_name)
        try:
            self._browser = browser_type.launch(headless=self.headless)
        except Exception as exc:  # pragma: no cover - depends on local install
            self._playwright.stop()
            raise WebsiteTimeoutError(f"Failed to launch {self.browser_name} browser: {exc}") from exc

        context_kwargs = {"accept_downloads": True}
        self._context = self._browser.new_context(**context_kwargs)
        self._context.set_default_timeout(self.default_timeout_ms)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
        finally:
            if self._playwright:
                self._playwright.stop()

    def new_page(self):
        if self._context is None:
            raise RuntimeError("ScraperSession must be used as a context manager")
        return self._context.new_page()

    @property
    def storage_state(self) -> dict:
        """Cookies/localStorage - used to detect & persist an authenticated session."""
        return self._context.storage_state()


@contextmanager
def translate_playwright_errors(site_label: str) -> Iterator[None]:
    """Map low-level Playwright exceptions to the app's typed error hierarchy."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    try:
        yield
    except PlaywrightTimeoutError as exc:
        logger.error("%s timed out: %s", site_label, exc)
        raise WebsiteTimeoutError(
            f"{site_label} did not respond in time. It may be slow or unreachable right now."
        ) from exc
    except PlaywrightError as exc:
        logger.error("%s automation error: %s", site_label, exc)
        raise WebsiteStructureChangedError(
            f"{site_label} page did not match the expected layout. "
            f"The website may have changed - selectors may need to be updated. Detail: {exc}"
        ) from exc
