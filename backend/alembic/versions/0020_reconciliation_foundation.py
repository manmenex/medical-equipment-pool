"""Roadmap PR22B -- Reconciliation Schema + Run/Snapshot Foundation

Revision ID: 0020_reconciliation_foundation
Revises: 0019_legacy_history_foundation
Create Date: 2026-08-23

Note on the revision id's shorter form: `alembic_version.version_num` is
`VARCHAR(32)` (see `0001_initial.py`); `0020_legacy_reconciliation_
foundation` (37 chars) does not fit. `0020_reconciliation_foundation`
(30 chars) is used instead -- shortened only for that constraint, not a
naming-convention change.

Roadmap PR22B (docs/design/PR22_LEGACY_DATA_RECONCILIATION_PLAN.md
§9.J, §11, §13-15, §17.2, §18, §20-22, §25, §36 -- OD-PR22-1 through
OD-PR22-7, all RESOLVED/OWNER APPROVED), refined by the PR22B
implementation task's own binding field contract. Introduces six new,
purely additive tables: `legacy_migration_authority_coverages`
(OD-PR22-7's governed two-boundary temporal-coverage approval
artifact), `legacy_reconciliation_runs` (one reconciliation attempt per
approved coverage artifact; `pending`/`running`/`completed`/`failed`
lifecycle; OD-PR22-3's forward-only supersession via
`supersedes_run_id`), `legacy_reconciliation_findings` (bounded,
DB-unconstrained `code`; closed `severity` domain; OD-PR22-2's
four-value `disposition` domain), `legacy_reconciliation_finding_events`
(indexed, referentially-enforced finding-to-`LegacyEquipmentEvent`
provenance junction table), `legacy_reconciliation_signoffs`
(OD-PR22-6's final sign-off artifact -- table shape only; no sign-off
logic, endpoint, service, or audit write exists anywhere in this
slice, that is PR22E's exclusive scope), and `legacy_bme_user_aliases`
(OD-PR22-4's display-only BME-name-to-User mapping, mirroring
`legacy_ward_aliases`'s exact shape). No existing table is modified.
This slice implements no analysis/detection engine (PR22C), no API,
and no frontend.

**Fresh-install vs. historical-upgrade convergence**, following the
exact discipline migrations `0015`-`0019` established (see those
migrations' own extensive docstrings for the full rationale -- not
restated here). `app.models.legacy_reconciliation` (registered in
`app/db/base.py`) already defines all six ORM models, so
`0001_initial.py`'s `Base.metadata.create_all()` already creates every
table on any brand-new install. This migration's own raw SQL is what
creates them on a database that historically applied `0001`-`0019`
before this slice existed. `_verify_schema_convergence()` below is the
same production-owned, fail-closed catalog classification pattern as
`0015`-`0019`'s (closed-world column/constraint/index equality,
index/constraint health gates, relation-scoped constraint lookups)
applied to all six tables -- every expected value captured empirically
against a real, freshly migrated PostgreSQL 16 database (this
repository's own local instance, migrated through `0019` first, then
these six tables created directly via `Base.metadata.create_all()` and
their catalog rows read back), never hand-guessed. Two auto-generated
foreign-key constraint names are truncated by PostgreSQL's own
NAMEDATALEN(63) limit
(`legacy_migration_authority_coverage_migration_authority_id_fkey`,
`legacy_reconciliation_finding_ev_legacy_equipment_event_id_fkey`) --
both captured and reproduced verbatim below exactly as PostgreSQL
itself generated them, not hand-shortened.

Only ever runs raw SQL against PostgreSQL (see 0002/0004/0011-0019's
identical dialect-gated pattern) -- SQLite tests create these tables via
`Base.metadata.create_all()` directly (`tests/conftest.py`), never via
this migration chain, so ORM model correctness alone is authoritative
there.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_reconciliation_foundation"
down_revision: Union[str, None] = "0019_legacy_history_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CREATE_COVERAGES = """
CREATE TABLE IF NOT EXISTS legacy_migration_authority_coverages (
    id UUID NOT NULL PRIMARY KEY,
    migration_authority_id UUID NOT NULL REFERENCES legacy_migration_authorities(id) ON DELETE RESTRICT,
    legacy_coverage_start TIMESTAMP WITH TIME ZONE NOT NULL,
    legacy_coverage_end TIMESTAMP WITH TIME ZONE NOT NULL,
    live_system_start TIMESTAMP WITH TIME ZONE NOT NULL,
    approval_basis VARCHAR(50) NOT NULL,
    approved_by_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    approved_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT ck_legacy_migration_authority_coverages_coverage_window
        CHECK (legacy_coverage_start <= legacy_coverage_end),
    CONSTRAINT ck_legacy_migration_authority_coverages_approval_basis
        CHECK (approval_basis IN ('explicit_owner_approval','explicit_administrator_approval'))
)
"""

_CREATE_COVERAGES_AUTHORITY_INDEX = """
CREATE INDEX IF NOT EXISTS ix_legacy_migration_authority_coverages_migration_authority_id
    ON legacy_migration_authority_coverages (migration_authority_id)
"""

_CREATE_COVERAGES_AUTHORITY_APPROVED_AT_INDEX = """
CREATE INDEX IF NOT EXISTS ix_legacy_migration_authority_coverages_authority_approved_at
    ON legacy_migration_authority_coverages (migration_authority_id, approved_at)
"""

_CREATE_RUNS = """
CREATE TABLE IF NOT EXISTS legacy_reconciliation_runs (
    id UUID NOT NULL PRIMARY KEY,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    version INTEGER NOT NULL DEFAULT 0,
    rule_version VARCHAR(50) NOT NULL,
    snapshot_as_of TIMESTAMP WITH TIME ZONE NOT NULL,
    created_by_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    failed_at TIMESTAMP WITH TIME ZONE,
    legacy_coverage_start TIMESTAMP WITH TIME ZONE NOT NULL,
    legacy_coverage_end TIMESTAMP WITH TIME ZONE NOT NULL,
    live_system_start TIMESTAMP WITH TIME ZONE NOT NULL,
    coverage_id UUID NOT NULL REFERENCES legacy_migration_authority_coverages(id) ON DELETE RESTRICT,
    supersedes_run_id UUID REFERENCES legacy_reconciliation_runs(id) ON DELETE RESTRICT,
    summary_total_findings INTEGER NOT NULL DEFAULT 0,
    summary_high INTEGER NOT NULL DEFAULT 0,
    summary_medium INTEGER NOT NULL DEFAULT 0,
    summary_low INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT ck_legacy_reconciliation_runs_status
        CHECK (status IN ('pending','running','completed','failed')),
    CONSTRAINT ck_legacy_reconciliation_runs_version CHECK (version >= 0),
    CONSTRAINT ck_legacy_reconciliation_runs_coverage_window
        CHECK (legacy_coverage_start <= legacy_coverage_end),
    CONSTRAINT ck_legacy_reconciliation_runs_no_self_supersession
        CHECK (supersedes_run_id IS NULL OR supersedes_run_id <> id),
    CONSTRAINT ck_legacy_reconciliation_runs_summary_total_findings CHECK (summary_total_findings >= 0),
    CONSTRAINT ck_legacy_reconciliation_runs_summary_high CHECK (summary_high >= 0),
    CONSTRAINT ck_legacy_reconciliation_runs_summary_medium CHECK (summary_medium >= 0),
    CONSTRAINT ck_legacy_reconciliation_runs_summary_low CHECK (summary_low >= 0)
)
"""

_CREATE_RUNS_CREATED_AT_INDEX = """
CREATE INDEX IF NOT EXISTS ix_legacy_reconciliation_runs_created_at
    ON legacy_reconciliation_runs (created_at)
"""

_CREATE_RUNS_STATUS_INDEX = """
CREATE INDEX IF NOT EXISTS ix_legacy_reconciliation_runs_status
    ON legacy_reconciliation_runs (status)
"""

_CREATE_RUNS_COVERAGE_INDEX = """
CREATE INDEX IF NOT EXISTS ix_legacy_reconciliation_runs_coverage_id
    ON legacy_reconciliation_runs (coverage_id)
"""

_CREATE_RUNS_SUPERSEDES_INDEX = """
CREATE INDEX IF NOT EXISTS ix_legacy_reconciliation_runs_supersedes_run_id
    ON legacy_reconciliation_runs (supersedes_run_id)
"""

_CREATE_FINDINGS = """
CREATE TABLE IF NOT EXISTS legacy_reconciliation_findings (
    id UUID NOT NULL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES legacy_reconciliation_runs(id) ON DELETE RESTRICT,
    code VARCHAR(50) NOT NULL,
    severity VARCHAR(10) NOT NULL,
    equipment_id UUID REFERENCES equipment(id) ON DELETE RESTRICT,
    evidence JSONB NOT NULL,
    rule_version VARCHAR(50) NOT NULL,
    disposition VARCHAR(30),
    disposed_by_user_id UUID REFERENCES users(id) ON DELETE RESTRICT,
    disposed_at TIMESTAMP WITH TIME ZONE,
    disposition_note TEXT,
    version INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT ck_legacy_reconciliation_findings_severity
        CHECK (severity IN ('high','medium','low')),
    CONSTRAINT ck_legacy_reconciliation_findings_disposition
        CHECK (disposition IS NULL OR disposition IN
            ('confirmed_valid','confirmed_duplicate','accepted_unresolved','requires_correction')),
    CONSTRAINT ck_legacy_reconciliation_findings_disposed_by_pair
        CHECK ((disposition IS NULL) = (disposed_by_user_id IS NULL)),
    CONSTRAINT ck_legacy_reconciliation_findings_disposed_at_pair
        CHECK ((disposition IS NULL) = (disposed_at IS NULL)),
    CONSTRAINT ck_legacy_reconciliation_findings_version CHECK (version >= 0)
)
"""

_CREATE_FINDINGS_RUN_INDEX = """
CREATE INDEX IF NOT EXISTS ix_legacy_reconciliation_findings_run_id
    ON legacy_reconciliation_findings (run_id)
"""

_CREATE_FINDINGS_RUN_DISPOSITION_INDEX = """
CREATE INDEX IF NOT EXISTS ix_legacy_reconciliation_findings_run_disposition
    ON legacy_reconciliation_findings (run_id, disposition)
"""

_CREATE_FINDINGS_RUN_CODE_INDEX = """
CREATE INDEX IF NOT EXISTS ix_legacy_reconciliation_findings_run_code
    ON legacy_reconciliation_findings (run_id, code)
"""

_CREATE_FINDINGS_EQUIPMENT_INDEX = """
CREATE INDEX IF NOT EXISTS ix_legacy_reconciliation_findings_equipment_id
    ON legacy_reconciliation_findings (equipment_id)
"""

_CREATE_FINDING_EVENTS = """
CREATE TABLE IF NOT EXISTS legacy_reconciliation_finding_events (
    id UUID NOT NULL PRIMARY KEY,
    finding_id UUID NOT NULL REFERENCES legacy_reconciliation_findings(id) ON DELETE RESTRICT,
    legacy_equipment_event_id UUID NOT NULL REFERENCES legacy_equipment_events(id) ON DELETE RESTRICT,
    CONSTRAINT uq_legacy_reconciliation_finding_events_finding_event
        UNIQUE (finding_id, legacy_equipment_event_id)
)
"""

_CREATE_FINDING_EVENTS_FINDING_INDEX = """
CREATE INDEX IF NOT EXISTS ix_legacy_reconciliation_finding_events_finding_id
    ON legacy_reconciliation_finding_events (finding_id)
"""

_CREATE_FINDING_EVENTS_EVENT_INDEX = """
CREATE INDEX IF NOT EXISTS ix_legacy_reconciliation_finding_events_event_id
    ON legacy_reconciliation_finding_events (legacy_equipment_event_id)
"""

_CREATE_SIGNOFFS = """
CREATE TABLE IF NOT EXISTS legacy_reconciliation_signoffs (
    id UUID NOT NULL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES legacy_reconciliation_runs(id) ON DELETE RESTRICT,
    signed_off_by_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    signed_off_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    attestation_summary JSONB NOT NULL,
    run_version_at_signoff INTEGER NOT NULL,
    CONSTRAINT uq_legacy_reconciliation_signoffs_run_id UNIQUE (run_id),
    CONSTRAINT ck_legacy_reconciliation_signoffs_run_version_at_signoff
        CHECK (run_version_at_signoff >= 0)
)
"""

_CREATE_BME_ALIASES = """
CREATE TABLE IF NOT EXISTS legacy_bme_user_aliases (
    id UUID NOT NULL PRIMARY KEY,
    raw_bme_name VARCHAR(150) NOT NULL,
    resolved_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_by_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT uq_legacy_bme_user_aliases_raw_bme_name UNIQUE (raw_bme_name)
)
"""

_GOVERNED_TABLES = (
    "legacy_migration_authority_coverages",
    "legacy_reconciliation_runs",
    "legacy_reconciliation_findings",
    "legacy_reconciliation_finding_events",
    "legacy_reconciliation_signoffs",
    "legacy_bme_user_aliases",
)

# Captured empirically against a real, freshly migrated PostgreSQL 16
# database (all six tables created directly via
# `Base.metadata.create_all()`, then their own catalog rows read back)
# -- mirrors 0015-0019's `_EXPECTED_COLUMNS` shape exactly: (data_type,
# udt_name, character_maximum_length, is_nullable, column_default).
_EXPECTED_COLUMNS = {
    "legacy_migration_authority_coverages": {
        "id": ("uuid", "uuid", None, "NO", None),
        "migration_authority_id": ("uuid", "uuid", None, "NO", None),
        "legacy_coverage_start": ("timestamp with time zone", "timestamptz", None, "NO", None),
        "legacy_coverage_end": ("timestamp with time zone", "timestamptz", None, "NO", None),
        "live_system_start": ("timestamp with time zone", "timestamptz", None, "NO", None),
        "approval_basis": ("character varying", "varchar", 50, "NO", None),
        "approved_by_user_id": ("uuid", "uuid", None, "NO", None),
        "approved_at": ("timestamp with time zone", "timestamptz", None, "NO", "now()"),
        "created_at": ("timestamp with time zone", "timestamptz", None, "NO", "now()"),
    },
    "legacy_reconciliation_runs": {
        "id": ("uuid", "uuid", None, "NO", None),
        "status": ("character varying", "varchar", 20, "NO", "'pending'::character varying"),
        "version": ("integer", "int4", None, "NO", "0"),
        "rule_version": ("character varying", "varchar", 50, "NO", None),
        "snapshot_as_of": ("timestamp with time zone", "timestamptz", None, "NO", None),
        "created_by_user_id": ("uuid", "uuid", None, "NO", None),
        "created_at": ("timestamp with time zone", "timestamptz", None, "NO", "now()"),
        "started_at": ("timestamp with time zone", "timestamptz", None, "YES", None),
        "completed_at": ("timestamp with time zone", "timestamptz", None, "YES", None),
        "failed_at": ("timestamp with time zone", "timestamptz", None, "YES", None),
        "legacy_coverage_start": ("timestamp with time zone", "timestamptz", None, "NO", None),
        "legacy_coverage_end": ("timestamp with time zone", "timestamptz", None, "NO", None),
        "live_system_start": ("timestamp with time zone", "timestamptz", None, "NO", None),
        "coverage_id": ("uuid", "uuid", None, "NO", None),
        "supersedes_run_id": ("uuid", "uuid", None, "YES", None),
        "summary_total_findings": ("integer", "int4", None, "NO", "0"),
        "summary_high": ("integer", "int4", None, "NO", "0"),
        "summary_medium": ("integer", "int4", None, "NO", "0"),
        "summary_low": ("integer", "int4", None, "NO", "0"),
    },
    "legacy_reconciliation_findings": {
        "id": ("uuid", "uuid", None, "NO", None),
        "run_id": ("uuid", "uuid", None, "NO", None),
        "code": ("character varying", "varchar", 50, "NO", None),
        "severity": ("character varying", "varchar", 10, "NO", None),
        "equipment_id": ("uuid", "uuid", None, "YES", None),
        "evidence": ("jsonb", "jsonb", None, "NO", None),
        "rule_version": ("character varying", "varchar", 50, "NO", None),
        "disposition": ("character varying", "varchar", 30, "YES", None),
        "disposed_by_user_id": ("uuid", "uuid", None, "YES", None),
        "disposed_at": ("timestamp with time zone", "timestamptz", None, "YES", None),
        "disposition_note": ("text", "text", None, "YES", None),
        "version": ("integer", "int4", None, "NO", "0"),
        "created_at": ("timestamp with time zone", "timestamptz", None, "NO", "now()"),
    },
    "legacy_reconciliation_finding_events": {
        "id": ("uuid", "uuid", None, "NO", None),
        "finding_id": ("uuid", "uuid", None, "NO", None),
        "legacy_equipment_event_id": ("uuid", "uuid", None, "NO", None),
    },
    "legacy_reconciliation_signoffs": {
        "id": ("uuid", "uuid", None, "NO", None),
        "run_id": ("uuid", "uuid", None, "NO", None),
        "signed_off_by_user_id": ("uuid", "uuid", None, "NO", None),
        "signed_off_at": ("timestamp with time zone", "timestamptz", None, "NO", "now()"),
        "attestation_summary": ("jsonb", "jsonb", None, "NO", None),
        "run_version_at_signoff": ("integer", "int4", None, "NO", None),
    },
    "legacy_bme_user_aliases": {
        "id": ("uuid", "uuid", None, "NO", None),
        "raw_bme_name": ("character varying", "varchar", 150, "NO", None),
        "resolved_user_id": ("uuid", "uuid", None, "NO", None),
        "created_by_user_id": ("uuid", "uuid", None, "NO", None),
        "created_at": ("timestamp with time zone", "timestamptz", None, "NO", "now()"),
    },
}

# Mirrors 0015-0019's `_EXPECTED_CONSTRAINTS` shape -- `pg_get_constraintdef()`
# renders every constraint kind uniformly, including PostgreSQL's own
# auto-generated PK/FK names (and their auto-truncated form where the
# naive name would exceed NAMEDATALEN 63, captured empirically below).
_EXPECTED_CONSTRAINTS = {
    "legacy_migration_authority_coverages": {
        "legacy_migration_authority_coverages_pkey": "PRIMARY KEY (id)",
        # NAMEDATALEN(63)-truncated auto-generated name -- PostgreSQL
        # itself drops the trailing "s" from "coverages" here, not a
        # hand-shortened name.
        "legacy_migration_authority_coverage_migration_authority_id_fkey": (
            "FOREIGN KEY (migration_authority_id) REFERENCES legacy_migration_authorities(id) ON DELETE RESTRICT"
        ),
        "legacy_migration_authority_coverages_approved_by_user_id_fkey": (
            "FOREIGN KEY (approved_by_user_id) REFERENCES users(id) ON DELETE RESTRICT"
        ),
        "ck_legacy_migration_authority_coverages_coverage_window": (
            "CHECK ((legacy_coverage_start <= legacy_coverage_end))"
        ),
        "ck_legacy_migration_authority_coverages_approval_basis": (
            "CHECK (((approval_basis)::text = ANY ((ARRAY['explicit_owner_approval'::character varying, "
            "'explicit_administrator_approval'::character varying])::text[])))"
        ),
    },
    "legacy_reconciliation_runs": {
        "legacy_reconciliation_runs_pkey": "PRIMARY KEY (id)",
        "legacy_reconciliation_runs_coverage_id_fkey": (
            "FOREIGN KEY (coverage_id) REFERENCES legacy_migration_authority_coverages(id) ON DELETE RESTRICT"
        ),
        "legacy_reconciliation_runs_created_by_user_id_fkey": (
            "FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT"
        ),
        "legacy_reconciliation_runs_supersedes_run_id_fkey": (
            "FOREIGN KEY (supersedes_run_id) REFERENCES legacy_reconciliation_runs(id) ON DELETE RESTRICT"
        ),
        "ck_legacy_reconciliation_runs_status": (
            "CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying, "
            "'completed'::character varying, 'failed'::character varying])::text[])))"
        ),
        "ck_legacy_reconciliation_runs_version": "CHECK ((version >= 0))",
        "ck_legacy_reconciliation_runs_coverage_window": (
            "CHECK ((legacy_coverage_start <= legacy_coverage_end))"
        ),
        "ck_legacy_reconciliation_runs_no_self_supersession": (
            "CHECK (((supersedes_run_id IS NULL) OR (supersedes_run_id <> id)))"
        ),
        "ck_legacy_reconciliation_runs_summary_total_findings": "CHECK ((summary_total_findings >= 0))",
        "ck_legacy_reconciliation_runs_summary_high": "CHECK ((summary_high >= 0))",
        "ck_legacy_reconciliation_runs_summary_medium": "CHECK ((summary_medium >= 0))",
        "ck_legacy_reconciliation_runs_summary_low": "CHECK ((summary_low >= 0))",
    },
    "legacy_reconciliation_findings": {
        "legacy_reconciliation_findings_pkey": "PRIMARY KEY (id)",
        "legacy_reconciliation_findings_run_id_fkey": (
            "FOREIGN KEY (run_id) REFERENCES legacy_reconciliation_runs(id) ON DELETE RESTRICT"
        ),
        "legacy_reconciliation_findings_equipment_id_fkey": (
            "FOREIGN KEY (equipment_id) REFERENCES equipment(id) ON DELETE RESTRICT"
        ),
        "legacy_reconciliation_findings_disposed_by_user_id_fkey": (
            "FOREIGN KEY (disposed_by_user_id) REFERENCES users(id) ON DELETE RESTRICT"
        ),
        "ck_legacy_reconciliation_findings_severity": (
            "CHECK (((severity)::text = ANY ((ARRAY['high'::character varying, 'medium'::character varying, "
            "'low'::character varying])::text[])))"
        ),
        "ck_legacy_reconciliation_findings_disposition": (
            "CHECK (((disposition IS NULL) OR ((disposition)::text = ANY "
            "((ARRAY['confirmed_valid'::character varying, 'confirmed_duplicate'::character varying, "
            "'accepted_unresolved'::character varying, 'requires_correction'::character varying])::text[]))))"
        ),
        "ck_legacy_reconciliation_findings_disposed_by_pair": (
            "CHECK (((disposition IS NULL) = (disposed_by_user_id IS NULL)))"
        ),
        "ck_legacy_reconciliation_findings_disposed_at_pair": (
            "CHECK (((disposition IS NULL) = (disposed_at IS NULL)))"
        ),
        "ck_legacy_reconciliation_findings_version": "CHECK ((version >= 0))",
    },
    "legacy_reconciliation_finding_events": {
        "legacy_reconciliation_finding_events_pkey": "PRIMARY KEY (id)",
        "legacy_reconciliation_finding_events_finding_id_fkey": (
            "FOREIGN KEY (finding_id) REFERENCES legacy_reconciliation_findings(id) ON DELETE RESTRICT"
        ),
        # NAMEDATALEN(63)-truncated auto-generated name -- PostgreSQL
        # itself shortens "finding_events" to "finding_ev" here, not a
        # hand-shortened name.
        "legacy_reconciliation_finding_ev_legacy_equipment_event_id_fkey": (
            "FOREIGN KEY (legacy_equipment_event_id) REFERENCES legacy_equipment_events(id) ON DELETE RESTRICT"
        ),
        "uq_legacy_reconciliation_finding_events_finding_event": (
            "UNIQUE (finding_id, legacy_equipment_event_id)"
        ),
    },
    "legacy_reconciliation_signoffs": {
        "legacy_reconciliation_signoffs_pkey": "PRIMARY KEY (id)",
        "legacy_reconciliation_signoffs_run_id_fkey": (
            "FOREIGN KEY (run_id) REFERENCES legacy_reconciliation_runs(id) ON DELETE RESTRICT"
        ),
        "legacy_reconciliation_signoffs_signed_off_by_user_id_fkey": (
            "FOREIGN KEY (signed_off_by_user_id) REFERENCES users(id) ON DELETE RESTRICT"
        ),
        "uq_legacy_reconciliation_signoffs_run_id": "UNIQUE (run_id)",
        "ck_legacy_reconciliation_signoffs_run_version_at_signoff": "CHECK ((run_version_at_signoff >= 0))",
    },
    "legacy_bme_user_aliases": {
        "legacy_bme_user_aliases_pkey": "PRIMARY KEY (id)",
        "legacy_bme_user_aliases_resolved_user_id_fkey": (
            "FOREIGN KEY (resolved_user_id) REFERENCES users(id) ON DELETE RESTRICT"
        ),
        "legacy_bme_user_aliases_created_by_user_id_fkey": (
            "FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT"
        ),
        "uq_legacy_bme_user_aliases_raw_bme_name": "UNIQUE (raw_bme_name)",
    },
}

# Mirrors 0015-0019's `_EXPECTED_INDEXES` shape.
_EXPECTED_INDEXES = {
    "legacy_migration_authority_coverages": {
        "legacy_migration_authority_coverages_pkey": (
            "CREATE UNIQUE INDEX legacy_migration_authority_coverages_pkey ON "
            "public.legacy_migration_authority_coverages USING btree (id)"
        ),
        "ix_legacy_migration_authority_coverages_migration_authority_id": (
            "CREATE INDEX ix_legacy_migration_authority_coverages_migration_authority_id ON "
            "public.legacy_migration_authority_coverages USING btree (migration_authority_id)"
        ),
        "ix_legacy_migration_authority_coverages_authority_approved_at": (
            "CREATE INDEX ix_legacy_migration_authority_coverages_authority_approved_at ON "
            "public.legacy_migration_authority_coverages USING btree (migration_authority_id, approved_at)"
        ),
    },
    "legacy_reconciliation_runs": {
        "legacy_reconciliation_runs_pkey": (
            "CREATE UNIQUE INDEX legacy_reconciliation_runs_pkey ON public.legacy_reconciliation_runs "
            "USING btree (id)"
        ),
        "ix_legacy_reconciliation_runs_created_at": (
            "CREATE INDEX ix_legacy_reconciliation_runs_created_at ON public.legacy_reconciliation_runs "
            "USING btree (created_at)"
        ),
        "ix_legacy_reconciliation_runs_status": (
            "CREATE INDEX ix_legacy_reconciliation_runs_status ON public.legacy_reconciliation_runs "
            "USING btree (status)"
        ),
        "ix_legacy_reconciliation_runs_coverage_id": (
            "CREATE INDEX ix_legacy_reconciliation_runs_coverage_id ON public.legacy_reconciliation_runs "
            "USING btree (coverage_id)"
        ),
        "ix_legacy_reconciliation_runs_supersedes_run_id": (
            "CREATE INDEX ix_legacy_reconciliation_runs_supersedes_run_id ON public.legacy_reconciliation_runs "
            "USING btree (supersedes_run_id)"
        ),
    },
    "legacy_reconciliation_findings": {
        "legacy_reconciliation_findings_pkey": (
            "CREATE UNIQUE INDEX legacy_reconciliation_findings_pkey ON public.legacy_reconciliation_findings "
            "USING btree (id)"
        ),
        "ix_legacy_reconciliation_findings_run_id": (
            "CREATE INDEX ix_legacy_reconciliation_findings_run_id ON public.legacy_reconciliation_findings "
            "USING btree (run_id)"
        ),
        "ix_legacy_reconciliation_findings_run_disposition": (
            "CREATE INDEX ix_legacy_reconciliation_findings_run_disposition ON "
            "public.legacy_reconciliation_findings USING btree (run_id, disposition)"
        ),
        "ix_legacy_reconciliation_findings_run_code": (
            "CREATE INDEX ix_legacy_reconciliation_findings_run_code ON public.legacy_reconciliation_findings "
            "USING btree (run_id, code)"
        ),
        "ix_legacy_reconciliation_findings_equipment_id": (
            "CREATE INDEX ix_legacy_reconciliation_findings_equipment_id ON "
            "public.legacy_reconciliation_findings USING btree (equipment_id)"
        ),
    },
    "legacy_reconciliation_finding_events": {
        "legacy_reconciliation_finding_events_pkey": (
            "CREATE UNIQUE INDEX legacy_reconciliation_finding_events_pkey ON "
            "public.legacy_reconciliation_finding_events USING btree (id)"
        ),
        "uq_legacy_reconciliation_finding_events_finding_event": (
            "CREATE UNIQUE INDEX uq_legacy_reconciliation_finding_events_finding_event ON "
            "public.legacy_reconciliation_finding_events USING btree (finding_id, legacy_equipment_event_id)"
        ),
        "ix_legacy_reconciliation_finding_events_finding_id": (
            "CREATE INDEX ix_legacy_reconciliation_finding_events_finding_id ON "
            "public.legacy_reconciliation_finding_events USING btree (finding_id)"
        ),
        "ix_legacy_reconciliation_finding_events_event_id": (
            "CREATE INDEX ix_legacy_reconciliation_finding_events_event_id ON "
            "public.legacy_reconciliation_finding_events USING btree (legacy_equipment_event_id)"
        ),
    },
    "legacy_reconciliation_signoffs": {
        "legacy_reconciliation_signoffs_pkey": (
            "CREATE UNIQUE INDEX legacy_reconciliation_signoffs_pkey ON "
            "public.legacy_reconciliation_signoffs USING btree (id)"
        ),
        "uq_legacy_reconciliation_signoffs_run_id": (
            "CREATE UNIQUE INDEX uq_legacy_reconciliation_signoffs_run_id ON "
            "public.legacy_reconciliation_signoffs USING btree (run_id)"
        ),
    },
    "legacy_bme_user_aliases": {
        "legacy_bme_user_aliases_pkey": (
            "CREATE UNIQUE INDEX legacy_bme_user_aliases_pkey ON public.legacy_bme_user_aliases USING btree (id)"
        ),
        "uq_legacy_bme_user_aliases_raw_bme_name": (
            "CREATE UNIQUE INDEX uq_legacy_bme_user_aliases_raw_bme_name ON public.legacy_bme_user_aliases "
            "USING btree (raw_bme_name)"
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
    """Mirrors `0019_legacy_history_foundation._verify_schema_convergence()`'s
    exact discipline and rationale, applied to all six new PR22B tables.
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
                f"{table}: unexpected column(s) not part of the PR22B design contract "
                f"(docs/design/PR22_LEGACY_DATA_RECONCILIATION_PLAN.md §9.J/§11/§13-15/§17.2/§36): "
                f"{sorted(unexpected_columns)}. An extra application column is never silently accepted "
                "merely because every expected column also exists."
            )
        unexpected_constraints = _unexpected_object_names(
            bind, _ACTUAL_CONSTRAINT_NAMES_SQL, table, _EXPECTED_CONSTRAINTS[table]
        )
        if unexpected_constraints:
            problems.append(
                f"{table}: unexpected constraint(s) not part of the PR22B design contract: "
                f"{sorted(unexpected_constraints)}."
            )
        unexpected_indexes = _unexpected_object_names(bind, _ACTUAL_INDEX_NAMES_SQL, table, _EXPECTED_INDEXES[table])
        if unexpected_indexes:
            problems.append(
                f"{table}: unexpected index(es) not part of the PR22B design contract: {sorted(unexpected_indexes)}."
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
            "Migration 0020 aborted: the existing PostgreSQL catalog diverges from the PR22B design "
            f"contract (docs/design/PR22_LEGACY_DATA_RECONCILIATION_PLAN.md §9.J/§11/§13-15/§17.2/§36) "
            f"in {len(problems)} way(s). Refusing to silently continue with an incompatible historical "
            "schema:\n\n" + "\n\n".join(problems)
        )


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    op.execute(sa.text(_CREATE_COVERAGES))
    op.execute(sa.text(_CREATE_COVERAGES_AUTHORITY_INDEX))
    op.execute(sa.text(_CREATE_COVERAGES_AUTHORITY_APPROVED_AT_INDEX))
    op.execute(sa.text(_CREATE_RUNS))
    op.execute(sa.text(_CREATE_RUNS_CREATED_AT_INDEX))
    op.execute(sa.text(_CREATE_RUNS_STATUS_INDEX))
    op.execute(sa.text(_CREATE_RUNS_COVERAGE_INDEX))
    op.execute(sa.text(_CREATE_RUNS_SUPERSEDES_INDEX))
    op.execute(sa.text(_CREATE_FINDINGS))
    op.execute(sa.text(_CREATE_FINDINGS_RUN_INDEX))
    op.execute(sa.text(_CREATE_FINDINGS_RUN_DISPOSITION_INDEX))
    op.execute(sa.text(_CREATE_FINDINGS_RUN_CODE_INDEX))
    op.execute(sa.text(_CREATE_FINDINGS_EQUIPMENT_INDEX))
    op.execute(sa.text(_CREATE_FINDING_EVENTS))
    op.execute(sa.text(_CREATE_FINDING_EVENTS_FINDING_INDEX))
    op.execute(sa.text(_CREATE_FINDING_EVENTS_EVENT_INDEX))
    op.execute(sa.text(_CREATE_SIGNOFFS))
    op.execute(sa.text(_CREATE_BME_ALIASES))
    _verify_schema_convergence(bind)


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    op.execute(sa.text("DROP TABLE IF EXISTS legacy_bme_user_aliases"))
    op.execute(sa.text("DROP TABLE IF EXISTS legacy_reconciliation_signoffs"))
    op.execute(sa.text("DROP TABLE IF EXISTS legacy_reconciliation_finding_events"))
    op.execute(sa.text("DROP TABLE IF EXISTS legacy_reconciliation_findings"))
    op.execute(sa.text("DROP TABLE IF EXISTS legacy_reconciliation_runs"))
    op.execute(sa.text("DROP TABLE IF EXISTS legacy_migration_authority_coverages"))
