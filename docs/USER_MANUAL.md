# User Manual

## Overview

The Medical Device Recall Monitor helps your biomedical/clinical
engineering team answer one question every week: **"Do any of the recalls
or alerts published this week affect equipment we actually own?"**

It does this by:

1. Pulling recall/alert records from the **FDA** and **ECRI** sources.
2. Comparing them against your **hospital inventory** spreadsheet.
3. Producing a **weekly Excel + PDF report** you can file, email, or
   present at your recall-review meeting.

## Navigation

The left-hand navigation rail has eight sections:

- **Dashboard** - at-a-glance counts and charts.
- **FDA Recalls** - search/download FDA recalls for a date range.
- **ECRI Alerts** - log in and download ECRI Alerts Tracker notices.
- **Inventory** - import/view your hospital equipment list.
- **Matching** - run the matching engine and review results.
- **Search** - free-form cross-table search.
- **Reports** - generate/download weekly Excel & PDF reports.
- **Settings** - thresholds, folders, theme, credentials, backups,
  scheduler.

## Typical weekly workflow

1. **FDA Recalls** → set the start/end date for the week → **Search FDA
   Recalls**. New recalls are saved to the local database; the table
   below shows everything on file (not just this week's search).
2. **ECRI Alerts** → if you haven't yet, click **Configure Login** to
   store your ECRI username/password (this is a one-time step; the app
   remembers it securely). Then set the date range and **Search ECRI
   Alerts**.
3. **Inventory** → only needed once, or whenever your equipment list
   changes: **Import Excel Inventory** and pick your `.xlsx`/`.xls`
   file. The importer automatically maps columns like "Asset #", "Mfr.",
   "Model No." etc. onto the fields the matching engine needs; any column
   it can't confidently map is kept as-is and just doesn't participate in
   matching.
4. **Matching** → optionally adjust the two thresholds, then **Run
   Matching**. Every FDA recall and ECRI alert on file is compared
   against your full inventory and classified as:
   - **Matched** (green) - high-confidence hit; investigate immediately.
   - **Possible Match** (amber) - worth a manual look.
   - **Not Matched** (red) - no similar inventory item found.

   The **Reason** column always explains *why* (e.g. "Exact model number
   match", "Product name similarity 82%").
5. **Reports** → pick Year / Month / Week, optionally filter by
   manufacturer/department/recall class, then **Generate Report**. This
   produces both:
   - `Recall_Report_<Year>_Week<N>.xlsx` - Summary sheet + FDA/ECRI/Matches
     detail sheets, each with Excel's AutoFilter enabled on the header row.
   - `Recall_Report_<Year>_Week<N>.pdf` - a print-ready version of the
     same data.

   Past reports are listed at the bottom of the page with **Open** buttons.

## Automating the weekly check

Instead of doing the above by hand every week, go to **Settings →
Automatic Scheduler**:

1. Choose a frequency (Daily / Weekly / Monthly) and a time of day.
2. Click **Save Schedule** - the app will now run the full
   FDA+ECRI+Matching+Report pipeline unattended at that cadence, as long
   as the application process is running (a hospital IT team would
   typically leave this running on a dedicated workstation or server).
3. **Run Check Now** lets you trigger the same pipeline immediately, e.g.
   to test your configuration.

Results always land in the same place as a manual run: refresh the
Dashboard afterward to see the updated counts, and check **Reports** for
the newly generated files.

## Understanding the Matching Engine

The engine looks for the single best-matching inventory item for every
recall/alert, trying these signals **in priority order** and stopping at
the first confident tier:

1. **UDI** exact match
2. **Model Number** exact match
3. **Catalog Number** exact match
4. **Manufacturer** exact match + similar product name
5. **Product Name** fuzzy similarity
6. **Fuzzy Matching** - overall similarity across manufacturer + product +
   model, as a last resort

The two thresholds in **Settings → Matching Engine** (or on the Matching
page itself) control the cutoffs:

- Score ≥ **Similarity Threshold** → **Matched**
- Score ≥ **Possible Match Threshold** (but below the above) → **Possible
  Match**
- Otherwise → **Not Matched**

Raise the Similarity Threshold if you're seeing false positives; lower it
(or lower the Possible Match Threshold) if you're worried about missing a
real match.

## Advanced Search

Use **Search** when you already know part of what you're looking for -
e.g. "show me everything from manufacturer 'Acme'" or "has recall number
Z-1234 been checked against our inventory?" It searches FDA recalls and
inventory items directly (results table shows which source each row came
from).

## Settings reference

| Setting | Effect |
|---|---|
| Similarity Threshold / Possible Match Threshold | Matching engine cutoffs (see above) |
| Download Folder | Where generated Excel/PDF reports are written |
| Auto Update | Whether the scheduler runs automatically |
| Auto Login | Whether ECRI sessions are silently re-authenticated when they expire |
| Theme | Dark or Light |
| ECRI Credentials | Change or remove the stored ECRI username/password |
| Database Backup | Copies the live SQLite database to a timestamped file in the backup folder |

## Data safety

- Every scrape, import, match run, login, and export is written to a
  daily log file under your configured `LOG_DIR` (one file per category:
  `login.log`, `download.log`, `import.log`, `matching.log`, `error.log`,
  `export.log`, plus a combined `app.log`).
- Use **Settings → Backup Database Now** regularly, or before a major
  inventory re-import, so you can roll back if something looks wrong.
