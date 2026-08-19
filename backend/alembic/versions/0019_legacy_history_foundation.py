"""Roadmap PR21A -- Historical Event Schema / Provenance Foundation

Revision ID: 0019_legacy_history_foundation
Revises: 0018_dry_run_plans
Create Date: 2026-08-19

Roadmap PR21A (docs/design/PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md
§8.1, §14, §24.2, §36). Introduces six new, purely additive tables:
`legacy_migration_authorities` (§24.2's `LegacyMigrationAuthority` --
one immutable, checksum-bound governance record per Owner-approved
historical migration snapshot), `legacy_equipment_events` (§8.1's
`LegacyEquipmentEvent` -- one independent, immutable historical
`ISSUE`/`RECEIVE` fact, never a paired `BorrowTransaction` row),
`legacy_equipment_event_source_refs` (§8.1's simplified 1:N provenance,
up to two refs per event), `legacy_ward_aliases` (§14's OD-PR21-4
Administrator-owned Ward alias mapping), and
`legacy_history_dry_run_plans`/`legacy_history_dry_run_plan_rows`
(§36's PR21-owned persisted dry-run plan, registered against
PR21-Foundation's generic provider interface, GitHub PR #100). No
existing table is modified, and no row is ever written into
`borrow_transactions` by this migration or by anything this slice adds
(§12's finding: direct `BorrowTransaction` representation of unpaired
legacy history is structurally impossible/unsafe). This slice does not
implement any parser, any SDC-sheet handling, or PR21D's execution --
`app.crud.legacy_history_dry_run_plan.insert_plan`/
`bulk_insert_plan_rows` have no production caller yet.

**Fresh-install vs. historical-upgrade convergence**, following the
exact discipline migrations `0015`-`0018` established (see those
migrations' own extensive docstrings for the full rationale -- not
restated here). `app.models.legacy_history` (registered in
`app/db/base.py`) already defines all six ORM models, so
`0001_initial.py`'s `Base.metadata.create_all()` already creates every
table on any brand-new install. This migration's own raw SQL is what
creates them on a database that historically applied `0001`-`0018`
before this slice existed. `_verify_schema_convergence()` below is the
same production-owned, fail-closed catalog classification pattern as
`0015`-`0018`'s (closed-world column/constraint/index equality,
index/constraint health gates, relation-scoped constraint lookups)
applied to all six tables -- every expected value captured empirically
against a real, freshly migrated PostgreSQL 16 database (this
repository's own local instance, migrated through `0018` first, then
these six tables created directly via `Base.metadata.create_all()` and
their catalog rows read back), never hand-guessed. Two FK constraint
names below are PostgreSQL's own auto-truncated defaults (NAMEDATALEN
63): `legacy_equipment_event_source_refs`'s FK to
`legacy_equipment_events` renders as
`legacy_equipment_event_source_re_legacy_equipment_event_id_fkey`, not
the naively-expected `..._source_refs_legacy_equipment_event_id_fkey`
-- captured empirically, not guessed, exactly like `0015`-`0018`'s own
truncated-name findings.

Only ever runs raw SQL against PostgreSQL (see 0002/0004/0011-0018's
identical dialect-gated pattern) -- SQLite tests create these tables via
`Base.metadata.create_all()` directly (`tests/conftest.py`), never via
this migration chain, so ORM model correctness alone is authoritative
there.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_legacy_history_foundation"
down_revision: Union[str, None] = "0018_dry_run_plans"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CREATE_MIGRATION_AUTHORITIES = """
CREATE TABLE IF NOT EXISTS legacy_migration_authorities (
    id UUID NOT NULL PRIMARY KEY,
    scope VARCHAR(100) NOT NULL,
    approved_workbook_sha256 VARCHAR(64) NOT NULL,
    approved_by_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    approved_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT uq_legacy_migration_authorities_checksum UNIQUE (approved_workbook_sha256),
    CONSTRAINT ck_legacy_migration_authorities_checksum_length CHECK (LENGTH(approved_workbook_sha256) = 64)
)
"""

_CREATE_EQUIPMENT_EVENTS = """
CREATE TABLE IF NOT EXISTS legacy_equipment_events (
    id UUID NOT NULL PRIMARY KEY,
    migration_authority_id UUID NOT NULL REFERENCES legacy_migration_authorities(id) ON DELETE RESTRICT,
    equipment_id UUID NOT NULL REFERENCES equipment(id) ON DELETE RESTRICT,
    event_type VARCHAR(10) NOT NULL,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    legacy_source_row_key VARCHAR(64) NOT NULL,
    legacy_order_reference VARCHAR(100),
    legacy_ward_text VARCHAR(150),
    resolved_ward_id UUID REFERENCES wards(id) ON DELETE RESTRICT,
    legacy_bme_name VARCHAR(150),
    import_session_id UUID NOT NULL REFERENCES import_sessions(id) ON DELETE RESTRICT,
    import_source_id UUID NOT NULL REFERENCES import_sources(id) ON DELETE RESTRICT,
    imported_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT ck_legacy_equipment_events_event_type CHECK (event_type IN ('ISSUE','RECEIVE')),
    CONSTRAINT uq_legacy_equipment_events_identity
        UNIQUE (migration_authority_id, event_type, legacy_source_row_key)
)
"""

_CREATE_EQUIPMENT_EVENTS_EQUIPMENT_INDEX = """
CREATE INDEX IF NOT EXISTS ix_legacy_equipment_events_equipment_id
    ON legacy_equipment_events (equipment_id)
"""

_CREATE_EQUIPMENT_EVENTS_SESSION_INDEX = """
CREATE INDEX IF NOT EXISTS ix_legacy_equipment_events_import_session_id
    ON legacy_equipment_events (import_session_id)
"""

_CREATE_EVENT_SOURCE_REFS = """
CREATE TABLE IF NOT EXISTS legacy_equipment_event_source_refs (
    id UUID NOT NULL PRIMARY KEY,
    legacy_equipment_event_id UUID NOT NULL REFERENCES legacy_equipment_events(id) ON DELETE RESTRICT,
    import_session_id UUID NOT NULL REFERENCES import_sessions(id) ON DELETE RESTRICT,
    import_source_id UUID NOT NULL REFERENCES import_sources(id) ON DELETE RESTRICT,
    source_checksum VARCHAR(128) NOT NULL,
    sheet_name VARCHAR(100) NOT NULL,
    source_row_number INTEGER NOT NULL,
    CONSTRAINT uq_legacy_equipment_event_source_refs_event_source_row
        UNIQUE (legacy_equipment_event_id, import_source_id, sheet_name, source_row_number)
)
"""

_CREATE_EVENT_SOURCE_REFS_EVENT_INDEX = """
CREATE INDEX IF NOT EXISTS ix_legacy_equipment_event_source_refs_event_id
    ON legacy_equipment_event_source_refs (legacy_equipment_event_id)
"""

_CREATE_WARD_ALIASES = """
CREATE TABLE IF NOT EXISTS legacy_ward_aliases (
    id UUID NOT NULL PRIMARY KEY,
    raw_alias VARCHAR(150) NOT NULL,
    ward_id UUID NOT NULL REFERENCES wards(id) ON DELETE RESTRICT,
    created_by_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT uq_legacy_ward_aliases_raw_alias UNIQUE (raw_alias)
)
"""

_CREATE_PLANS = """
CREATE TABLE IF NOT EXISTS legacy_history_dry_run_plans (
    id UUID NOT NULL PRIMARY KEY,
    import_session_id UUID NOT NULL REFERENCES import_sessions(id) ON DELETE RESTRICT,
    import_source_id UUID NOT NULL REFERENCES import_sources(id) ON DELETE RESTRICT,
    migration_authority_id UUID NOT NULL REFERENCES legacy_migration_authorities(id) ON DELETE RESTRICT,
    source_checksum VARCHAR(128) NOT NULL,
    accepted_validation_job_id UUID NOT NULL,
    dry_run_job_id UUID NOT NULL,
    ruleset_version VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    confirmed_at TIMESTAMP WITH TIME ZONE,
    confirmed_by_user_id UUID REFERENCES users(id) ON DELETE RESTRICT,
    summary_total_rows INTEGER NOT NULL DEFAULT 0,
    summary_issue_events INTEGER NOT NULL DEFAULT 0,
    summary_receive_events INTEGER NOT NULL DEFAULT 0,
    summary_warnings INTEGER NOT NULL DEFAULT 0,
    summary_blocking_conflicts INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT ck_legacy_history_dry_run_plans_status
        CHECK (status IN ('active','superseded','consumed','failed')),
    CONSTRAINT ck_legacy_history_dry_run_plans_confirmed_pair
        CHECK ((confirmed_at IS NULL) = (confirmed_by_user_id IS NULL)),
    CONSTRAINT ck_legacy_history_dry_run_plans_summary_total_rows CHECK (summary_total_rows >= 0),
    CONSTRAINT ck_legacy_history_dry_run_plans_summary_issue_events CHECK (summary_issue_events >= 0),
    CONSTRAINT ck_legacy_history_dry_run_plans_summary_receive_events CHECK (summary_receive_events >= 0),
    CONSTRAINT ck_legacy_history_dry_run_plans_summary_warnings CHECK (summary_warnings >= 0),
    CONSTRAINT ck_legacy_history_dry_run_plans_summary_blocking_conflicts
        CHECK (summary_blocking_conflicts >= 0),
    CONSTRAINT fk_legacy_history_dry_run_plans_accepted_validation_job
        FOREIGN KEY (import_session_id, accepted_validation_job_id)
        REFERENCES import_jobs(import_session_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_legacy_history_dry_run_plans_dry_run_job
        FOREIGN KEY (import_session_id, dry_run_job_id)
        REFERENCES import_jobs(import_session_id, id) ON DELETE RESTRICT,
    CONSTRAINT uq_legacy_history_dry_run_plans_session_dry_run_job
        UNIQUE (import_session_id, dry_run_job_id)
)
"""

_CREATE_PLANS_ONE_ACTIVE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_legacy_history_dry_run_plans_one_active_per_session
    ON legacy_history_dry_run_plans (import_session_id) WHERE status = 'active'
"""

_CREATE_PLAN_ROWS = """
CREATE TABLE IF NOT EXISTS legacy_history_dry_run_plan_rows (
    id UUID NOT NULL PRIMARY KEY,
    dry_run_plan_id UUID NOT NULL REFERENCES legacy_history_dry_run_plans(id) ON DELETE RESTRICT,
    source_row_number INTEGER NOT NULL,
    event_type VARCHAR(10) NOT NULL,
    legacy_source_row_key VARCHAR(64) NOT NULL,
    normalized_values JSONB,
    warnings JSONB,
    CONSTRAINT ck_legacy_history_dry_run_plan_rows_event_type CHECK (event_type IN ('ISSUE','RECEIVE')),
    CONSTRAINT uq_legacy_history_dry_run_plan_rows_plan_event_row
        UNIQUE (dry_run_plan_id, event_type, source_row_number)
)
"""

_CREATE_PLAN_ROWS_PLAN_ID_INDEX = """
CREATE INDEX IF NOT EXISTS ix_legacy_history_dry_run_plan_rows_plan_id
    ON legacy_history_dry_run_plan_rows (dry_run_plan_id)
"""

_GOVERNED_TABLES = (
    "legacy_migration_authorities",
    "legacy_equipment_events",
    "legacy_equipment_event_source_refs",
    "legacy_ward_aliases",
    "legacy_history_dry_run_plans",
    "legacy_history_dry_run_plan_rows",
)

# Captured empirically against a real, freshly migrated PostgreSQL 16
# database (all six tables created directly via
# `Base.metadata.create_all()`, then their own catalog rows read back)
# -- mirrors 0015-0018's `_EXPECTED_COLUMNS` shape exactly: (data_type,
# udt_name, character_maximum_length, is_nullable, column_default).
_EXPECTED_COLUMNS = {
    "legacy_migration_authorities": {
        "id": ("uuid", "uuid", None, "NO", None),
        "scope": ("character varying", "varchar", 100, "NO", None),
        "approved_workbook_sha256": ("character varying", "varchar", 64, "NO", None),
        "approved_by_user_id": ("uuid", "uuid", None, "NO", None),
        "approved_at": ("timestamp with time zone", "timestamptz", None, "NO", "now()"),
        "created_at": ("timestamp with time zone", "timestamptz", None, "NO", "now()"),
    },
    "legacy_equipment_events": {
        "id": ("uuid", "uuid", None, "NO", None),
        "migration_authority_id": ("uuid", "uuid", None, "NO", None),
        "equipment_id": ("uuid", "uuid", None, "NO", None),
        "event_type": ("character varying", "varchar", 10, "NO", None),
        "occurred_at": ("timestamp with time zone", "timestamptz", None, "NO", None),
        "legacy_source_row_key": ("character varying", "varchar", 64, "NO", None),
        "legacy_order_reference": ("character varying", "varchar", 100, "YES", None),
        "legacy_ward_text": ("character varying", "varchar", 150, "YES", None),
        "resolved_ward_id": ("uuid", "uuid", None, "YES", None),
        "legacy_bme_name": ("character varying", "varchar", 150, "YES", None),
        "import_session_id": ("uuid", "uuid", None, "NO", None),
        "import_source_id": ("uuid", "uuid", None, "NO", None),
        "imported_at": ("timestamp with time zone", "timestamptz", None, "NO", "now()"),
    },
    "legacy_equipment_event_source_refs": {
        "id": ("uuid", "uuid", None, "NO", None),
        "legacy_equipment_event_id": ("uuid", "uuid", None, "NO", None),
        "import_session_id": ("uuid", "uuid", None, "NO", None),
        "import_source_id": ("uuid", "uuid", None, "NO", None),
        "source_checksum": ("character varying", "varchar", 128, "NO", None),
        "sheet_name": ("character varying", "varchar", 100, "NO", None),
        "source_row_number": ("integer", "int4", None, "NO", None),
    },
    "legacy_ward_aliases": {
        "id": ("uuid", "uuid", None, "NO", None),
        "raw_alias": ("character varying", "varchar", 150, "NO", None),
        "ward_id": ("uuid", "uuid", None, "NO", None),
        "created_by_user_id": ("uuid", "uuid", None, "NO", None),
        "created_at": ("timestamp with time zone", "timestamptz", None, "NO", "now()"),
    },
    "legacy_history_dry_run_plans": {
        "id": ("uuid", "uuid", None, "NO", None),
        "import_session_id": ("uuid", "uuid", None, "NO", None),
        "import_source_id": ("uuid", "uuid", None, "NO", None),
        "migration_authority_id": ("uuid", "uuid", None, "NO", None),
        "source_checksum": ("character varying", "varchar", 128, "NO", None),
        "accepted_validation_job_id": ("uuid", "uuid", None, "NO", None),
        "dry_run_job_id": ("uuid", "uuid", None, "NO", None),
        "ruleset_version": ("character varying", "varchar", 50, "NO", None),
        "status": ("character varying", "varchar", 20, "NO", "'active'::character varying"),
        "created_at": ("timestamp with time zone", "timestamptz", None, "NO", "now()"),
        "confirmed_at": ("timestamp with time zone", "timestamptz", None, "YES", None),
        "confirmed_by_user_id": ("uuid", "uuid", None, "YES", None),
        "summary_total_rows": ("integer", "int4", None, "NO", "0"),
        "summary_issue_events": ("integer", "int4", None, "NO", "0"),
        "summary_receive_events": ("integer", "int4", None, "NO", "0"),
        "summary_warnings": ("integer", "int4", None, "NO", "0"),
        "summary_blocking_conflicts": ("integer", "int4", None, "NO", "0"),
    },
    "legacy_history_dry_run_plan_rows": {
        "id": ("uuid", "uuid", None, "NO", None),
        "dry_run_plan_id": ("uuid", "uuid", None, "NO", None),
        "source_row_number": ("integer", "int4", None, "NO", None),
        "event_type": ("character varying", "varchar", 10, "NO", None),
        "legacy_source_row_key": ("character varying", "varchar", 64, "NO", None),
        "normalized_values": ("jsonb", "jsonb", None, "YES", None),
        "warnings": ("jsonb", "jsonb", None, "YES", None),
    },
}

# Mirrors 0015-0018's `_EXPECTED_CONSTRAINTS` shape -- `pg_get_constraintdef()`
# renders every constraint kind uniformly, including PostgreSQL's own
# auto-generated PK/FK names (and their auto-truncated form where the
# naive name would exceed NAMEDATALEN 63, captured empirically below).
_EXPECTED_CONSTRAINTS = {
    "legacy_migration_authorities": {
        "legacy_migration_authorities_pkey": "PRIMARY KEY (id)",
        "legacy_migration_authorities_approved_by_user_id_fkey": (
            "FOREIGN KEY (approved_by_user_id) REFERENCES users(id) ON DELETE RESTRICT"
        ),
        "uq_legacy_migration_authorities_checksum": "UNIQUE (approved_workbook_sha256)",
        "ck_legacy_migration_authorities_checksum_length": (
            "CHECK ((length((approved_workbook_sha256)::text) = 64))"
        ),
    },
    "legacy_equipment_events": {
        "legacy_equipment_events_pkey": "PRIMARY KEY (id)",
        "legacy_equipment_events_migration_authority_id_fkey": (
            "FOREIGN KEY (migration_authority_id) REFERENCES legacy_migration_authorities(id) ON DELETE RESTRICT"
        ),
        "legacy_equipment_events_equipment_id_fkey": (
            "FOREIGN KEY (equipment_id) REFERENCES equipment(id) ON DELETE RESTRICT"
        ),
        "legacy_equipment_events_resolved_ward_id_fkey": (
            "FOREIGN KEY (resolved_ward_id) REFERENCES wards(id) ON DELETE RESTRICT"
        ),
        "legacy_equipment_events_import_session_id_fkey": (
            "FOREIGN KEY (import_session_id) REFERENCES import_sessions(id) ON DELETE RESTRICT"
        ),
        "legacy_equipment_events_import_source_id_fkey": (
            "FOREIGN KEY (import_source_id) REFERENCES import_sources(id) ON DELETE RESTRICT"
        ),
        "uq_legacy_equipment_events_identity": (
            "UNIQUE (migration_authority_id, event_type, legacy_source_row_key)"
        ),
        "ck_legacy_equipment_events_event_type": (
            "CHECK (((event_type)::text = ANY ((ARRAY['ISSUE'::character varying, "
            "'RECEIVE'::character varying])::text[])))"
        ),
    },
    "legacy_equipment_event_source_refs": {
        "legacy_equipment_event_source_refs_pkey": "PRIMARY KEY (id)",
        # PostgreSQL's own NAMEDATALEN-63 auto-truncation of the naive
        # `legacy_equipment_event_source_refs_legacy_equipment_event_id_fkey`
        # -- captured empirically, not guessed.
        "legacy_equipment_event_source_re_legacy_equipment_event_id_fkey": (
            "FOREIGN KEY (legacy_equipment_event_id) REFERENCES legacy_equipment_events(id) ON DELETE RESTRICT"
        ),
        "legacy_equipment_event_source_refs_import_session_id_fkey": (
            "FOREIGN KEY (import_session_id) REFERENCES import_sessions(id) ON DELETE RESTRICT"
        ),
        "legacy_equipment_event_source_refs_import_source_id_fkey": (
            "FOREIGN KEY (import_source_id) REFERENCES import_sources(id) ON DELETE RESTRICT"
        ),
        "uq_legacy_equipment_event_source_refs_event_source_row": (
            "UNIQUE (legacy_equipment_event_id, import_source_id, sheet_name, source_row_number)"
        ),
    },
    "legacy_ward_aliases": {
        "legacy_ward_aliases_pkey": "PRIMARY KEY (id)",
        "legacy_ward_aliases_ward_id_fkey": "FOREIGN KEY (ward_id) REFERENCES wards(id) ON DELETE RESTRICT",
        "legacy_ward_aliases_created_by_user_id_fkey": (
            "FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT"
        ),
        "uq_legacy_ward_aliases_raw_alias": "UNIQUE (raw_alias)",
    },
    "legacy_history_dry_run_plans": {
        "legacy_history_dry_run_plans_pkey": "PRIMARY KEY (id)",
        "legacy_history_dry_run_plans_import_session_id_fkey": (
            "FOREIGN KEY (import_session_id) REFERENCES import_sessions(id) ON DELETE RESTRICT"
        ),
        "legacy_history_dry_run_plans_import_source_id_fkey": (
            "FOREIGN KEY (import_source_id) REFERENCES import_sources(id) ON DELETE RESTRICT"
        ),
        "legacy_history_dry_run_plans_migration_authority_id_fkey": (
            "FOREIGN KEY (migration_authority_id) REFERENCES legacy_migration_authorities(id) ON DELETE RESTRICT"
        ),
        "legacy_history_dry_run_plans_confirmed_by_user_id_fkey": (
            "FOREIGN KEY (confirmed_by_user_id) REFERENCES users(id) ON DELETE RESTRICT"
        ),
        "fk_legacy_history_dry_run_plans_accepted_validation_job": (
            "FOREIGN KEY (import_session_id, accepted_validation_job_id) REFERENCES "
            "import_jobs(import_session_id, id) ON DELETE RESTRICT"
        ),
        "fk_legacy_history_dry_run_plans_dry_run_job": (
            "FOREIGN KEY (import_session_id, dry_run_job_id) REFERENCES "
            "import_jobs(import_session_id, id) ON DELETE RESTRICT"
        ),
        "uq_legacy_history_dry_run_plans_session_dry_run_job": "UNIQUE (import_session_id, dry_run_job_id)",
        "ck_legacy_history_dry_run_plans_status": (
            "CHECK (((status)::text = ANY ((ARRAY['active'::character varying, "
            "'superseded'::character varying, 'consumed'::character varying, "
            "'failed'::character varying])::text[])))"
        ),
        "ck_legacy_history_dry_run_plans_confirmed_pair": (
            "CHECK (((confirmed_at IS NULL) = (confirmed_by_user_id IS NULL)))"
        ),
        "ck_legacy_history_dry_run_plans_summary_total_rows": "CHECK ((summary_total_rows >= 0))",
        "ck_legacy_history_dry_run_plans_summary_issue_events": "CHECK ((summary_issue_events >= 0))",
        "ck_legacy_history_dry_run_plans_summary_receive_events": "CHECK ((summary_receive_events >= 0))",
        "ck_legacy_history_dry_run_plans_summary_warnings": "CHECK ((summary_warnings >= 0))",
        "ck_legacy_history_dry_run_plans_summary_blocking_conflicts": (
            "CHECK ((summary_blocking_conflicts >= 0))"
        ),
    },
    "legacy_history_dry_run_plan_rows": {
        "legacy_history_dry_run_plan_rows_pkey": "PRIMARY KEY (id)",
        "legacy_history_dry_run_plan_rows_dry_run_plan_id_fkey": (
            "FOREIGN KEY (dry_run_plan_id) REFERENCES legacy_history_dry_run_plans(id) ON DELETE RESTRICT"
        ),
        "uq_legacy_history_dry_run_plan_rows_plan_event_row": (
            "UNIQUE (dry_run_plan_id, event_type, source_row_number)"
        ),
        "ck_legacy_history_dry_run_plan_rows_event_type": (
            "CHECK (((event_type)::text = ANY ((ARRAY['ISSUE'::character varying, "
            "'RECEIVE'::character varying])::text[])))"
        ),
    },
}

# Mirrors 0015-0018's `_EXPECTED_INDEXES` shape.
_EXPECTED_INDEXES = {
    "legacy_migration_authorities": {
        "legacy_migration_authorities_pkey": (
            "CREATE UNIQUE INDEX legacy_migration_authorities_pkey ON "
            "public.legacy_migration_authorities USING btree (id)"
        ),
        "uq_legacy_migration_authorities_checksum": (
            "CREATE UNIQUE INDEX uq_legacy_migration_authorities_checksum ON "
            "public.legacy_migration_authorities USING btree (approved_workbook_sha256)"
        ),
    },
    "legacy_equipment_events": {
        "legacy_equipment_events_pkey": (
            "CREATE UNIQUE INDEX legacy_equipment_events_pkey ON public.legacy_equipment_events USING btree (id)"
        ),
        "uq_legacy_equipment_events_identity": (
            "CREATE UNIQUE INDEX uq_legacy_equipment_events_identity ON public.legacy_equipment_events "
            "USING btree (migration_authority_id, event_type, legacy_source_row_key)"
        ),
        "ix_legacy_equipment_events_equipment_id": (
            "CREATE INDEX ix_legacy_equipment_events_equipment_id ON public.legacy_equipment_events "
            "USING btree (equipment_id)"
        ),
        "ix_legacy_equipment_events_import_session_id": (
            "CREATE INDEX ix_legacy_equipment_events_import_session_id ON public.legacy_equipment_events "
            "USING btree (import_session_id)"
        ),
    },
    "legacy_equipment_event_source_refs": {
        "legacy_equipment_event_source_refs_pkey": (
            "CREATE UNIQUE INDEX legacy_equipment_event_source_refs_pkey ON "
            "public.legacy_equipment_event_source_refs USING btree (id)"
        ),
        "uq_legacy_equipment_event_source_refs_event_source_row": (
            "CREATE UNIQUE INDEX uq_legacy_equipment_event_source_refs_event_source_row ON "
            "public.legacy_equipment_event_source_refs USING btree (legacy_equipment_event_id, "
            "import_source_id, sheet_name, source_row_number)"
        ),
        "ix_legacy_equipment_event_source_refs_event_id": (
            "CREATE INDEX ix_legacy_equipment_event_source_refs_event_id ON "
            "public.legacy_equipment_event_source_refs USING btree (legacy_equipment_event_id)"
        ),
    },
    "legacy_ward_aliases": {
        "legacy_ward_aliases_pkey": (
            "CREATE UNIQUE INDEX legacy_ward_aliases_pkey ON public.legacy_ward_aliases USING btree (id)"
        ),
        "uq_legacy_ward_aliases_raw_alias": (
            "CREATE UNIQUE INDEX uq_legacy_ward_aliases_raw_alias ON public.legacy_ward_aliases "
            "USING btree (raw_alias)"
        ),
    },
    "legacy_history_dry_run_plans": {
        "legacy_history_dry_run_plans_pkey": (
            "CREATE UNIQUE INDEX legacy_history_dry_run_plans_pkey ON public.legacy_history_dry_run_plans "
            "USING btree (id)"
        ),
        "uq_legacy_history_dry_run_plans_session_dry_run_job": (
            "CREATE UNIQUE INDEX uq_legacy_history_dry_run_plans_session_dry_run_job ON "
            "public.legacy_history_dry_run_plans USING btree (import_session_id, dry_run_job_id)"
        ),
        "uq_legacy_history_dry_run_plans_one_active_per_session": (
            "CREATE UNIQUE INDEX uq_legacy_history_dry_run_plans_one_active_per_session ON "
            "public.legacy_history_dry_run_plans USING btree (import_session_id) "
            "WHERE ((status)::text = 'active'::text)"
        ),
    },
    "legacy_history_dry_run_plan_rows": {
        "legacy_history_dry_run_plan_rows_pkey": (
            "CREATE UNIQUE INDEX legacy_history_dry_run_plan_rows_pkey ON "
            "public.legacy_history_dry_run_plan_rows USING btree (id)"
        ),
        "uq_legacy_history_dry_run_plan_rows_plan_event_row": (
            "CREATE UNIQUE INDEX uq_legacy_history_dry_run_plan_rows_plan_event_row ON "
            "public.legacy_history_dry_run_plan_rows USING btree (dry_run_plan_id, event_type, "
            "source_row_number)"
        ),
        "ix_legacy_history_dry_run_plan_rows_plan_id": (
            "CREATE INDEX ix_legacy_history_dry_run_plan_rows_plan_id ON "
            "public.legacy_history_dry_run_plan_rows USING btree (dry_run_plan_id)"
        ),
    },
}

_MISSING = "missing"
_COMPATIBLE = "compatible"
_INCOMPATIBLE_DEFINITION = "incompatible_definition"
_INCOMPATIBLE_HEALTH = "incompatible_health"

_COLUMN_SQL = sa.text(
    "SELECT data_type, udt_name, character_maximum_length, is_nullable, column_default "
    "FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
)
_CONSTRAINT_DEF_SQL = sa.text(
    "SELECT pg_get_constraintdef(oid), convalidated FROM pg_constraint "
    "WHERE conrelid = (:t)::regclass AND conname = :name"
)
_INDEX_ROW_SQL = sa.text(
    """
    SELECT ix.indexdef, i.indisvalid, i.indisready
    FROM pg_indexes ix
    JOIN pg_class c ON c.relname = ix.indexname AND c.relnamespace = 'public'::regnamespace
    JOIN pg_index i ON i.indexrelid = c.oid
    WHERE ix.schemaname = 'public' AND ix.indexname = :name
    """
)
_ACTUAL_COLUMN_NAMES_SQL = sa.text(
    "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :t"
)
_ACTUAL_CONSTRAINT_NAMES_SQL = sa.text(
    "SELECT conname FROM pg_constraint WHERE conrelid = (:t)::regclass AND contype IN ('p', 'f', 'u', 'c')"
)
_ACTUAL_INDEX_NAMES_SQL = sa.text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = :t")


def _unexpected_object_names(bind, sql, table: str, expected_names) -> set[str]:
    actual_names = {row[0] for row in bind.execute(sql, {"t": table})}
    return actual_names - set(expected_names)


def _classify_column(bind, table: str, column: str, expected: tuple) -> tuple[str, tuple | None]:
    row = bind.execute(_COLUMN_SQL, {"t": table, "c": column}).one_or_none()
    if row is None:
        return _MISSING, None
    actual = (row.data_type, row.udt_name, row.character_maximum_length, row.is_nullable, row.column_default)
    return (_COMPATIBLE if actual == expected else _INCOMPATIBLE_DEFINITION), actual


def _classify_constraint(bind, table: str, name: str, expected_def: str) -> tuple[str, tuple[str, bool] | None]:
    row = bind.execute(_CONSTRAINT_DEF_SQL, {"t": table, "name": name}).one_or_none()
    if row is None:
        return _MISSING, None
    condef, convalidated = row
    if condef != expected_def:
        return _INCOMPATIBLE_DEFINITION, (condef, convalidated)
    if not convalidated:
        return _INCOMPATIBLE_HEALTH, (condef, convalidated)
    return _COMPATIBLE, (condef, convalidated)


def _classify_index(bind, name: str, expected_def: str) -> tuple[str, tuple[str, bool, bool] | None]:
    row = bind.execute(_INDEX_ROW_SQL, {"name": name}).one_or_none()
    if row is None:
        return _MISSING, None
    if row.indexdef != expected_def:
        return _INCOMPATIBLE_DEFINITION, (row.indexdef, row.indisvalid, row.indisready)
    if not (row.indisvalid and row.indisready):
        return _INCOMPATIBLE_HEALTH, (row.indexdef, row.indisvalid, row.indisready)
    return _COMPATIBLE, (row.indexdef, row.indisvalid, row.indisready)


def _verify_schema_convergence(bind) -> None:
    """Mirrors `0018_dry_run_plans._verify_schema_convergence()`'s exact
    discipline and rationale, applied to all six new PR21A tables.
    Required invariant: `expected_governed_objects ==
    actual_governed_objects` -- exact closed-world equality, per table.
    Any non-COMPATIBLE classification aborts the migration with every
    mismatch described concretely; nothing is ever silently dropped,
    renamed, rebuilt, or coerced. Runs inside Alembic's single
    per-invocation transaction, so raising here rolls back every DDL
    statement this migration issued, leaving the pre-migration schema
    completely unchanged."""
    problems: list[str] = []

    for table in _GOVERNED_TABLES:
        unexpected_columns = _unexpected_object_names(bind, _ACTUAL_COLUMN_NAMES_SQL, table, _EXPECTED_COLUMNS[table])
        if unexpected_columns:
            problems.append(
                f"{table}: unexpected column(s) not part of the PR21A design contract "
                f"(docs/design/PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md §8.1/§14/§24.2/§36): "
                f"{sorted(unexpected_columns)}. An extra application column is never silently accepted "
                "merely because every expected column also exists."
            )
        unexpected_constraints = _unexpected_object_names(
            bind, _ACTUAL_CONSTRAINT_NAMES_SQL, table, _EXPECTED_CONSTRAINTS[table]
        )
        if unexpected_constraints:
            problems.append(
                f"{table}: unexpected constraint(s) not part of the PR21A design contract: "
                f"{sorted(unexpected_constraints)}."
            )
        unexpected_indexes = _unexpected_object_names(bind, _ACTUAL_INDEX_NAMES_SQL, table, _EXPECTED_INDEXES[table])
        if unexpected_indexes:
            problems.append(
                f"{table}: unexpected index(es) not part of the PR21A design contract: {sorted(unexpected_indexes)}."
            )

        for column, expected in _EXPECTED_COLUMNS[table].items():
            kind, actual = _classify_column(bind, table, column, expected)
            if kind == _MISSING:
                problems.append(
                    f"{table}.{column}: column does not exist even after this migration's own CREATE "
                    "TABLE ran -- this indicates an internal migration bug, not a pre-existing "
                    "incompatible schema."
                )
            elif kind == _INCOMPATIBLE_DEFINITION:
                problems.append(
                    f"{table}.{column}: column exists but diverges from the design contract.\n"
                    f"    Expected (data_type, udt_name, char_max_length, is_nullable, column_default) = {expected!r}\n"
                    f"    Actual                                                                        = {actual!r}"
                )

        for name, expected_def in _EXPECTED_CONSTRAINTS[table].items():
            kind, actual = _classify_constraint(bind, table, name, expected_def)
            if kind == _MISSING:
                problems.append(
                    f"{table}: constraint '{name}' does not exist on this table even after this "
                    "migration's own DDL ran -- this indicates an internal migration bug, not a "
                    "pre-existing incompatible schema."
                )
            elif kind == _INCOMPATIBLE_DEFINITION:
                actual_def, _validated = actual
                problems.append(
                    f"{table}: constraint '{name}' exists on this table but its definition diverges.\n"
                    f"    Expected: {expected_def}\n"
                    f"    Actual:   {actual_def}"
                )
            elif kind == _INCOMPATIBLE_HEALTH:
                actual_def, validated = actual
                problems.append(
                    f"{table}: constraint '{name}' matches its expected definition but is not "
                    f"validated (pg_constraint.convalidated={validated})."
                )

        for name, expected_def in _EXPECTED_INDEXES[table].items():
            kind, actual = _classify_index(bind, name, expected_def)
            if kind == _MISSING:
                problems.append(
                    f"{table}: index '{name}' does not exist even after this migration's own CREATE "
                    "INDEX ran -- this indicates an internal migration bug, not a pre-existing "
                    "incompatible schema."
                )
            elif kind == _INCOMPATIBLE_DEFINITION:
                actual_def, _valid, _ready = actual
                problems.append(
                    f"{table}: index '{name}' exists but its definition diverges (CREATE INDEX IF "
                    "NOT EXISTS silently no-ops against a same-named index regardless of its actual "
                    "definition).\n"
                    f"    Expected: {expected_def}\n"
                    f"    Actual:   {actual_def}"
                )
            elif kind == _INCOMPATIBLE_HEALTH:
                actual_def, valid, ready = actual
                problems.append(
                    f"{table}: index '{name}' matches its expected definition but is not usable "
                    f"(pg_index.indisvalid={valid}, indisready={ready})."
                )

    if problems:
        raise RuntimeError(
            "Migration 0019 aborted: the existing PostgreSQL catalog diverges from the PR21A design "
            f"contract (docs/design/PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md §8.1/§14/§24.2/§36) "
            f"in {len(problems)} way(s). Refusing to silently continue with an incompatible historical "
            "schema:\n\n" + "\n\n".join(problems)
        )


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    op.execute(sa.text(_CREATE_MIGRATION_AUTHORITIES))
    op.execute(sa.text(_CREATE_EQUIPMENT_EVENTS))
    op.execute(sa.text(_CREATE_EQUIPMENT_EVENTS_EQUIPMENT_INDEX))
    op.execute(sa.text(_CREATE_EQUIPMENT_EVENTS_SESSION_INDEX))
    op.execute(sa.text(_CREATE_EVENT_SOURCE_REFS))
    op.execute(sa.text(_CREATE_EVENT_SOURCE_REFS_EVENT_INDEX))
    op.execute(sa.text(_CREATE_WARD_ALIASES))
    op.execute(sa.text(_CREATE_PLANS))
    op.execute(sa.text(_CREATE_PLANS_ONE_ACTIVE_INDEX))
    op.execute(sa.text(_CREATE_PLAN_ROWS))
    op.execute(sa.text(_CREATE_PLAN_ROWS_PLAN_ID_INDEX))
    _verify_schema_convergence(bind)


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    op.execute(sa.text("DROP TABLE IF EXISTS legacy_history_dry_run_plan_rows"))
    op.execute(sa.text("DROP TABLE IF EXISTS legacy_history_dry_run_plans"))
    op.execute(sa.text("DROP TABLE IF EXISTS legacy_ward_aliases"))
    op.execute(sa.text("DROP TABLE IF EXISTS legacy_equipment_event_source_refs"))
    op.execute(sa.text("DROP TABLE IF EXISTS legacy_equipment_events"))
    op.execute(sa.text("DROP TABLE IF EXISTS legacy_migration_authorities"))
