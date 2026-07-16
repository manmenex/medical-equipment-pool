# Installation Guide

## 1. Prerequisites

- Python 3.12 or newer
- Windows 10/11 (recommended for Windows Credential Manager integration),
  macOS, or Linux
- ~500 MB free disk space (PySide6 + a Playwright browser)
- Internet access to `accessdata.fda.gov`, `api.fda.gov`, and `sts.ecri.org`

## 2. Get the code

```bash
git clone <this-repository-url>
cd medical-equipment-pool
```

## 3. Create a virtual environment

```bash
python -m venv .venv
```

Activate it:

- Windows (PowerShell): `.venv\Scripts\Activate.ps1`
- Windows (cmd): `.venv\Scripts\activate.bat`
- macOS / Linux: `source .venv/bin/activate`

## 4. Install dependencies

```bash
pip install -r requirements.txt
```

## 5. Install the Playwright browser

Playwright needs at least one real browser binary; Chromium is what the
app is configured to use by default:

```bash
python -m playwright install chromium
```

(On Linux, Playwright may print a list of missing OS packages the first
time - install those with your distro's package manager if prompted.)

## 6. Configure the app

```bash
cp .env.example .env
```

Open `.env` and adjust as needed:

- `DATABASE_PATH`, `LOG_DIR`, `DOWNLOAD_DIR`, `BACKUP_DIR` - where the app
  keeps its data. Defaults are fine for a single-workstation install.
- `FDA_SEARCH_URL`, `ECRI_LOGIN_URL`, `ECRI_ALERTS_URL` - only change if
  your hospital uses a mirrored/internal URL.
- `FUZZY_MATCH_THRESHOLD` / `POSSIBLE_MATCH_THRESHOLD` - starting
  similarity thresholds (can also be changed later from Settings).
- `SCHEDULER_ENABLED`, `SCHEDULER_FREQUENCY`, `SCHEDULER_HOUR`,
  `SCHEDULER_MINUTE` - automatic weekly-check cadence.

**Never** put ECRI credentials in `.env` or any other file - the app will
prompt for them on first launch and store them in the OS credential vault.

## 7. Run it

```bash
python -m app.main
```

The first launch will:

1. Create the SQLite database and folder structure under the paths from
   `.env`.
2. Prompt for ECRI credentials (you can also skip this and configure it
   later from the ECRI page or Settings).

## 8. Run the test suite

```bash
pytest
```

GUI smoke tests use Qt's `offscreen` platform plugin automatically and
will run in headless CI without a display.

## 9. Load the sample data (optional, for a demo/eval install)

```bash
python scripts/generate_sample_data.py
```

This (re)writes `resources/sample_inventory.xlsx` and `resources/sample.db`
plus one example report in `resources/example_reports/`. To explore the
app pre-populated, copy `resources/sample.db` over the path in
`DATABASE_PATH` before launching.

## 10. Build a standalone executable (PyInstaller)

```bash
python build_tools/build.py
```

This produces `dist/MedicalDeviceRecallMonitor/` - copy that whole folder
to the target machine. Two things are **not** bundled by PyInstaller and
must be handled separately on the target machine:

- **Playwright's browser binary.** Either run
  `python -m playwright install chromium` once on the target machine (if
  Python/pip are present there), or copy your dev machine's
  `~/.cache/ms-playwright` (Linux/macOS) / `%USERPROFILE%\AppData\Local\ms-playwright`
  (Windows) folder alongside the build and set the `PLAYWRIGHT_BROWSERS_PATH`
  environment variable to point at it before launching.
- **The `.env` file.** Ship a production `.env` next to the executable
  (the packaged `.env.example` is a template, not a working config).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| App hangs on first launch | ECRI login dialog is a modal window waiting for input | Bring the window to front, or click "Cancel" to configure ECRI later from Settings |
| `NetworkUnavailableError` | No internet connection | Check the network connection; the app checks connectivity before every scrape |
| `WebsiteStructureChangedError` on FDA/ECRI search | The target site's HTML changed | See the "Important limitation" section in `README.md` - update the relevant selector strategy |
| `LoginFailedError` for ECRI | Wrong/expired credentials | Settings → ECRI Credentials → Change Credentials |
| `MissingColumnsError` on Excel import | The spreadsheet has no column that maps to "Asset Number" | Rename the asset ID column, or add a synonym to `app/utils/excel_mapper.py` |
| Keyring warnings on Linux | No D-Bus/Secret Service session (common on headless servers) | Expected - the app automatically falls back to its AES-encrypted local credential file |
