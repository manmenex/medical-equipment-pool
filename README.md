# Medical Device Recall Monitor

A desktop application for hospital biomedical/clinical engineering teams to
automatically monitor **FDA Medical Device Recalls** and **ECRI Alerts
Tracker** notices, compare them against the hospital's own equipment
inventory, and generate weekly recall-exposure reports.

Built with **Python 3.12+**, **PySide6**, **SQLite**, **Playwright**,
**RapidFuzz**, and **APScheduler**.

---

## What it does

| # | Function | Summary |
|---|----------|---------|
| 1 | FDA Scraper | Automates the FDA CDRH recall search (`res.cfm`) for a date range, with a resilient openFDA REST API fallback. |
| 2 | ECRI Scraper | Logs into `sts.ecri.org` with securely-stored credentials and scrapes the Alerts Tracker; auto re-logs-in on session expiry. |
| 3 | Inventory Import | Imports the hospital's Excel inventory (`.xlsx`/`.xls`) with automatic column-name mapping. |
| 4 | Matching Engine | RapidFuzz-powered priority cascade (UDI → Model # → Catalog # → Manufacturer → Product Name → Fuzzy) with a configurable similarity threshold. |
| 5 | Weekly Check | Auto-computes Week 1-4 periods (day 1-7, 8-14, 15-21, 22-end) for a chosen month/year. |
| 6 | Reports | Excel + PDF weekly reports (`Recall_Report_<Year>_Week<N>.xlsx/.pdf`) with summary + filterable detail tables. |
| 7 | Dashboard | KPIs + charts (by manufacturer, by month, by recall class). |
| 8 | Search | Cross-table advanced search (manufacturer, model, asset #, recall #, product, department, status). |
| 9 | Settings | Thresholds, download folder, auto-update/login, theme, DB backup. |
| 10 | Scheduler | APScheduler daily/weekly/monthly automatic checks. |
| 11 | Logging | Daily-rotating audit logs (login, download, import, matching, error, export). |
| 12 | Error Handling | Typed exceptions for offline/timeout/site-change/login-failure/bad-Excel scenarios, surfaced as plain-language dialogs. |

## Project layout

```
app/
    main.py                 Application entrypoint
    config/                 .env loading -> typed Settings
    database/               SQLite schema + connection manager + migrations
    models/                 Dataclasses shared by every layer
    scraper/                Playwright automation (FDA, ECRI) + shared session helper
    services/                Business logic (credentials, matching, periods, reports, ...)
    reports/                 Excel (openpyxl) + PDF (reportlab) renderers
    scheduler/               APScheduler wiring
    ui/                      PySide6 windows/pages/widgets
    utils/                   Logging, validation, exceptions, Excel column mapping
tests/                       pytest unit + GUI smoke tests
build_tools/                 PyInstaller spec + build script
scripts/                     Sample-data generator
resources/                   Sample Excel inventory, sample SQLite DB, example reports
docs/                        Installation guide + user manual
```

See [`docs/INSTALL.md`](docs/INSTALL.md) for setup and
[`docs/USER_MANUAL.md`](docs/USER_MANUAL.md) for day-to-day usage.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium

cp .env.example .env               # then edit paths/URLs as needed

python -m app.main
```

Run the test suite:

```bash
pytest
```

Generate the bundled sample data (sample inventory workbook, sample SQLite
DB, and one example weekly report) yourself:

```bash
python scripts/generate_sample_data.py
```

## Security notes

- ECRI credentials are **never hardcoded**. They are captured once via a
  login dialog and stored through the `keyring` package, which uses the
  **Windows Credential Manager** on Windows (macOS Keychain / Freedesktop
  Secret Service elsewhere). If no OS vault is available (e.g. a headless
  Linux box running only the scheduler), an AES-encrypted local file
  fallback is used instead - see `app/services/credential_service.py`.
- All SQLite access goes through parametrized queries
  (`app/database/db.py`); no SQL is ever built by string concatenation.
- Uploaded Excel files and scraped pages are validated before use
  (`app/utils/validators.py`, `app/utils/exceptions.py`).

## Important limitation: scraper selectors

`www.accessdata.fda.gov` and `sts.ecri.org` were not reachable from the
sandboxed environment this project was built in (network policy blocked
the hosts), so the Playwright selectors in `app/scraper/fda.py` and
`app/scraper/ecri.py` were written defensively - multiple fallback
locator strategies plus a clear `WebsiteStructureChangedError` if none
match - but **could not be interactively verified against the live
DOM**. Before the first production run:

1. Run the FDA/ECRI pages once with `PLAYWRIGHT_HEADLESS=false` in `.env`
   and watch the browser fill the form.
2. If a selector doesn't resolve, add/adjust an entry in
   `_SelectorStrategies` (FDA) or `_LoginSelectors` / `_ListingSelectors`
   (ECRI) - each is a ranked list of locator strategies, so you can add a
   new one without touching the rest of the scraper.
3. FDA additionally falls back automatically to the public, documented
   openFDA REST API (`api.fda.gov/device/recall.json`) if the HTML form
   can't be parsed, so weekly checks keep working even if `res.cfm`'s
   markup changes.

## License

Internal hospital tooling - no license file included; adapt as needed for
your organization.
