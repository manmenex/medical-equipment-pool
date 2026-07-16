-- ---------------------------------------------------------------------------
-- Medical Device Recall Monitor - SQLite schema
-- All tables use an explicit INTEGER PRIMARY KEY (rowid alias) and every
-- query in app/database/db.py uses parametrized "?" placeholders, so no
-- string-built SQL ever reaches sqlite3.execute() (SQL-injection prevention).
-- ---------------------------------------------------------------------------

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- FDA recalls
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fda_recalls (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    recall_number       TEXT NOT NULL,
    recall_class        TEXT,
    product             TEXT,
    product_code        TEXT,
    manufacturer        TEXT,
    reason              TEXT,
    date_initiated      TEXT,
    date_posted         TEXT,
    date_terminated     TEXT,
    status              TEXT,
    distribution        TEXT,
    quantity            TEXT,
    model_number        TEXT,
    catalog_number      TEXT,
    udi                 TEXT,
    k_numbers           TEXT,
    event_id            TEXT,
    recall_url          TEXT,
    root_cause          TEXT,
    action_taken        TEXT,
    raw_data            TEXT,               -- JSON blob: full raw record
    fetched_at          TEXT NOT NULL,
    UNIQUE (recall_number)
);

CREATE INDEX IF NOT EXISTS idx_fda_manufacturer ON fda_recalls (manufacturer);
CREATE INDEX IF NOT EXISTS idx_fda_date_initiated ON fda_recalls (date_initiated);
CREATE INDEX IF NOT EXISTS idx_fda_class ON fda_recalls (recall_class);

-- ---------------------------------------------------------------------------
-- ECRI alerts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ecri_alerts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_number        TEXT NOT NULL,
    title               TEXT,
    manufacturer        TEXT,
    product             TEXT,
    model_number        TEXT,
    catalog_number      TEXT,
    hazard_level        TEXT,
    alert_type          TEXT,
    date_issued         TEXT,
    status              TEXT,
    summary             TEXT,
    alert_url           TEXT,
    raw_data            TEXT,               -- JSON blob: every column found on the page
    fetched_at          TEXT NOT NULL,
    UNIQUE (alert_number)
);

CREATE INDEX IF NOT EXISTS idx_ecri_manufacturer ON ecri_alerts (manufacturer);
CREATE INDEX IF NOT EXISTS idx_ecri_date_issued ON ecri_alerts (date_issued);

-- ---------------------------------------------------------------------------
-- Hospital inventory
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inventory_items (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_number        TEXT NOT NULL,
    equipment_code      TEXT,
    device_name         TEXT,
    manufacturer        TEXT,
    brand               TEXT,
    model_number        TEXT,
    catalog_number      TEXT,
    udi                 TEXT,
    serial_number       TEXT,
    department          TEXT,
    location            TEXT,
    purchase_date       TEXT,
    status              TEXT,
    extra_fields        TEXT,               -- JSON blob: any unmapped source columns
    imported_at         TEXT NOT NULL,
    UNIQUE (asset_number)
);

CREATE INDEX IF NOT EXISTS idx_inv_manufacturer ON inventory_items (manufacturer);
CREATE INDEX IF NOT EXISTS idx_inv_model ON inventory_items (model_number);
CREATE INDEX IF NOT EXISTS idx_inv_department ON inventory_items (department);

-- ---------------------------------------------------------------------------
-- Match results
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS match_results (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    recall_source           TEXT NOT NULL,      -- 'FDA' | 'ECRI'
    recall_id               INTEGER,
    recall_number           TEXT NOT NULL,
    inventory_id            INTEGER,
    hospital_asset_number   TEXT,
    manufacturer            TEXT,
    model                   TEXT,
    confidence_score        REAL NOT NULL,
    status                  TEXT NOT NULL,       -- 'Matched' | 'Possible Match' | 'Not Matched'
    method                  TEXT NOT NULL,
    reason                  TEXT,
    report_period_start     TEXT,
    report_period_end       TEXT,
    checked_at              TEXT NOT NULL,
    FOREIGN KEY (inventory_id) REFERENCES inventory_items (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_match_status ON match_results (status);
CREATE INDEX IF NOT EXISTS idx_match_period ON match_results (report_period_start, report_period_end);
CREATE INDEX IF NOT EXISTS idx_match_recall_number ON match_results (recall_number);

-- ---------------------------------------------------------------------------
-- Weekly report runs (audit of each generated report)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS report_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    period_label        TEXT NOT NULL,       -- e.g. 2026_Week2
    year                INTEGER NOT NULL,
    month               INTEGER NOT NULL,
    week_number         INTEGER NOT NULL,
    start_date          TEXT NOT NULL,
    end_date            TEXT NOT NULL,
    total_fda           INTEGER DEFAULT 0,
    total_ecri          INTEGER DEFAULT 0,
    total_matched       INTEGER DEFAULT 0,
    total_possible      INTEGER DEFAULT 0,
    total_not_matched   INTEGER DEFAULT 0,
    excel_path          TEXT,
    pdf_path            TEXT,
    generated_at        TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Application settings (key/value; mirrors + overrides .env at runtime)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_settings (
    key                 TEXT PRIMARY KEY,
    value               TEXT,
    updated_at          TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Audit log (mirrors the day-based file logs into a queryable table for the
-- in-app "Logs" viewer)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    category            TEXT NOT NULL,   -- login, download, import, matching, error, export
    message             TEXT NOT NULL,
    detail              TEXT,
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_category ON audit_log (category);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log (created_at);

-- ---------------------------------------------------------------------------
-- Schema version, used by app/database/migrations.py
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_version (
    version             INTEGER NOT NULL
);
