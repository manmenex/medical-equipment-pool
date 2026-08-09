"""Roadmap PR19A1 -- legacy import foundation physical schema

Revision ID: 0015_import_foundation
Revises: 0014_index_naming_convergence
Create Date: 2026-08-04

Roadmap PR19A1 (docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md §4, §4.5,
§4.6, §8), architecture-approved via the merged Design PR #83. Introduces
four new, purely additive tables: `import_sessions`, `import_sources`,
`import_jobs`, `import_row_errors`. No existing table is modified. No
`ImportAdapter`/parser/validation/execution/frontend code ships with this
slice (§25) -- schema, session/source lifecycle CAS, source registration
and freeze, the composite ownership FK, and cursor pagination only.

**Fresh-install vs. historical-upgrade convergence (§8).** `app.models.
import_session` is now registered in `app/db/base.py`, so
`0001_initial.py`'s `Base.metadata.create_all(bind=bind)` already creates
all four tables on any brand-new install. This migration's own raw SQL
below is what creates these tables on a database that already historically
applied `0001`-`0014` *before* this slice existed (the only path where
`0001`'s `create_all()` could not have created them). `CREATE TABLE/INDEX
IF NOT EXISTS` makes the fresh-install path's re-application of this
migration's DDL a no-op against objects that already exist under the
expected name.

**PR84-H1R: name-based `IF NOT EXISTS` is not itself a compatibility
proof.** A same-named pre-existing object (table, column, constraint, or
index) can silently differ in the property that actually matters --
wrong column type, wrong nullability, wrong server default, an index or
FK/UNIQUE constraint that shares a name but not a definition, or an index
that is present, correctly defined, and still unusable
(`pg_index.indisvalid`/`indisready = false`, e.g. from an interrupted
`CREATE INDEX CONCURRENTLY`). `CREATE ... IF NOT EXISTS` would silently
skip creation in every one of those cases and the migration would
"succeed" over an incompatible historical schema. `_verify_schema_
convergence()` below is this migration's own, production-owned defense
against exactly that: after every `CREATE`/`ALTER` statement above has run
(whether it just created the object fresh or no-op'd against something
already there), it re-reads the *actual* PostgreSQL catalog for every
column, constraint (CHECK/UNIQUE/FK/PK -- `pg_get_constraintdef()` is
uniform across constraint kinds), and index (`pg_indexes.indexdef` +
`pg_index.indisvalid`/`indisready`) this migration governs, and classifies
each as MISSING / COMPATIBLE / INCOMPATIBLE against the literal expected
values in `_EXPECTED_COLUMNS`/`_EXPECTED_CONSTRAINTS`/`_EXPECTED_INDEXES`
(captured once, empirically, against a real fresh-installed PostgreSQL 16
database -- never hand-guessed). Any non-COMPATIBLE classification aborts
the migration with an actionable `RuntimeError` naming the specific
table/object/expected/actual mismatch. Nothing is ever silently dropped,
renamed, rebuilt, or coerced -- the default for an ambiguous or
incompatible pre-existing object is fail closed, matching the discipline
migrations 0011/0013/0014 already established for their own governed
objects (index/constraint semantic-definition + health-state verification
before any transformation, never name/presence alone).

**Index health is a required, independent gate**, exactly as migration
0014's `_IndexVerifier`/`_ConstraintVerifier` already require for their own
renamed objects: an index matching its expected `indexdef` byte-for-byte is
still classified INCOMPATIBLE if `indisvalid` or `indisready` is false --
its name and definition matching is not sufficient proof it is usable.

**PR84-H1R2: the contract is closed-world equality, not `expected ⊆
actual`.** Verifying that every expected object exists and is correct is
not sufficient on its own -- a pre-existing historical table could carry
every expected column/constraint/index *plus* an extra one (e.g. an
additional `UNIQUE(checksum)` on `import_sources`) that changes write
behavior without touching anything this migration explicitly checks.
`_verify_schema_convergence()` therefore also collects every *actual*
governed column/constraint/index name per table and rejects any name not
present in `_EXPECTED_COLUMNS`/`_EXPECTED_CONSTRAINTS`/`_EXPECTED_INDEXES`
-- `expected_governed_objects == actual_governed_objects`, both
directions. The governed-object boundary is explicit and narrow: columns
via `information_schema.columns`; constraints via `pg_constraint` filtered
to `contype IN ('p','f','u','c')` (every kind this design ever declares --
no EXCLUDE constraints exist here); indexes via `pg_indexes`, which already
lists exactly the application-visible indexes for a table, including the
ones PostgreSQL auto-creates to back a PRIMARY KEY/UNIQUE constraint --
`_EXPECTED_INDEXES` already names those backing indexes explicitly (e.g.
`import_sessions_pkey`, `import_sources_import_session_id_key`), so no
special-casing is needed to tell them apart from "real" indexes. No
PostgreSQL-internal or TOAST object is ever part of this comparison.

**PR84-H1R3: constraint lookups are relation-scoped by construction.**
Unlike index names (schema-unique in PostgreSQL, so `_INDEX_ROW_SQL`'s
`schemaname = 'public' AND indexname = :name` is already unambiguous),
constraint names are only unique *within* a relation -- the same name can
legitimately exist on two different tables. Every constraint lookup here
therefore requires `conrelid = (:t)::regclass` alongside `conname = :name`
(`_CONSTRAINT_DEF_SQL`, `_classify_constraint()`'s `table` parameter, and
the composite-FK existence pre-check in `upgrade()`); `_classify_
constraint()` has no signature that accepts a bare name, so an unscoped
lookup is impossible by construction, not merely a convention callers must
remember. Without this, a same-named constraint on an unrelated table (or
`fk_import_sessions_current_validation_job` existing anywhere except
`import_sessions`) could satisfy an unscoped `WHERE conname = ...` and
falsely classify the *target* table as already having a constraint it
never had. The lookup also fetches `pg_constraint.convalidated`, rejecting
a same-named-and-defined-but-`NOT VALID` constraint exactly as the index
health gate above rejects an `indisvalid = false` index.

The regression-test suite (`tests/test_postgres_integration.py`) exercises
this migration's own classification logic directly (via the real `alembic`
CLI against deliberately-mutated pre-existing schemas), not a separate
test-only comparison -- this migration's `_verify_schema_convergence()` is
the single place compatibility is enforced; the tests verify its behavior,
they do not duplicate it.

Only ever runs raw SQL against PostgreSQL (see 0002/0004/0011/0012/0013/
0014's identical dialect-gated pattern) -- SQLite tests create these tables
via `Base.metadata.create_all()` directly (`tests/conftest.py`), never via
this migration chain, so ORM model correctness alone is authoritative there.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_import_foundation"
down_revision: Union[str, None] = "0014_index_naming_convergence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CREATE_IMPORT_SESSIONS = """
CREATE TABLE IF NOT EXISTS import_sessions (
    id UUID NOT NULL PRIMARY KEY,
    dataset_type VARCHAR(100) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'created',
    version INTEGER NOT NULL DEFAULT 0,
    created_by_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    idempotency_key VARCHAR(200),
    notes TEXT,
    current_validation_job_id UUID,
    validated_at TIMESTAMPTZ,
    dry_run_completed_at TIMESTAMPTZ,
    executed_at TIMESTAMPTZ,
    terminal_at TIMESTAMPTZ,
    retention_purged_at TIMESTAMPTZ,
    source_bytes_deleted_at TIMESTAMPTZ,
    retention_cleanup_claimed_by UUID,
    retention_cleanup_claim_expires_at TIMESTAMPTZ,
    total_rows INTEGER,
    valid_rows INTEGER,
    invalid_rows INTEGER,
    warning_rows INTEGER,
    imported_rows INTEGER,
    failure_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_import_sessions_status CHECK (
        status IN ('created','validating','validated','validation_failed',
                   'dry_run_running','dry_run_completed','dry_run_failed',
                   'executing','completed','failed','cancelled')
    ),
    CONSTRAINT uq_import_sessions_dataset_idempotency UNIQUE (dataset_type, idempotency_key),
    CONSTRAINT ck_import_sessions_notes_length CHECK (LENGTH(notes) <= 4000),
    CONSTRAINT ck_import_sessions_failure_reason_length CHECK (LENGTH(failure_reason) <= 2000)
)
"""

_CREATE_IMPORT_SOURCES = """
CREATE TABLE IF NOT EXISTS import_sources (
    id UUID NOT NULL PRIMARY KEY,
    import_session_id UUID NOT NULL UNIQUE REFERENCES import_sessions(id) ON DELETE RESTRICT,
    status VARCHAR(20) NOT NULL DEFAULT 'registered',
    frozen_at TIMESTAMPTZ,
    checksum VARCHAR(128) NOT NULL,
    byte_size BIGINT NOT NULL,
    content_type VARCHAR(255),
    filename VARCHAR(255),
    source_version VARCHAR(100),
    options_fingerprint VARCHAR(64) NOT NULL,
    source_fingerprint VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_import_sources_status CHECK (status IN ('registered','frozen')),
    CONSTRAINT ck_import_sources_checksum_length CHECK (LENGTH(checksum) >= 32)
)
"""

_CREATE_IMPORT_JOBS = """
CREATE TABLE IF NOT EXISTS import_jobs (
    id UUID NOT NULL PRIMARY KEY,
    import_session_id UUID NOT NULL REFERENCES import_sessions(id) ON DELETE RESTRICT,
    job_type VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    attempt_number INTEGER NOT NULL,
    lease_owner UUID,
    lease_generation INTEGER NOT NULL DEFAULT 1,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_message TEXT,
    ruleset_version VARCHAR(50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_import_jobs_job_type CHECK (job_type IN ('validate','dry_run','execute')),
    CONSTRAINT ck_import_jobs_status CHECK (status IN ('pending','running','succeeded','failed','abandoned')),
    CONSTRAINT uq_import_jobs_session_id UNIQUE (import_session_id, id),
    CONSTRAINT uq_import_jobs_session_job_type_attempt UNIQUE (import_session_id, job_type, attempt_number),
    CONSTRAINT ck_import_jobs_error_message_length CHECK (LENGTH(error_message) <= 2000)
)
"""

_CREATE_IMPORT_ROW_ERRORS = """
CREATE TABLE IF NOT EXISTS import_row_errors (
    id UUID NOT NULL PRIMARY KEY,
    import_job_id UUID NOT NULL REFERENCES import_jobs(id) ON DELETE RESTRICT,
    row_number INTEGER,
    field VARCHAR(100),
    error_code VARCHAR(100) NOT NULL,
    message TEXT NOT NULL,
    severity VARCHAR(10) NOT NULL DEFAULT 'error',
    CONSTRAINT ck_import_row_errors_severity CHECK (severity IN ('error','warning'))
)
"""

# §4.5: the composite ownership foreign key, added after both tables exist
# (import_jobs must exist first for its own UNIQUE(import_session_id, id)
# to be a valid FK target). MATCH SIMPLE (PostgreSQL's default) -- not
# evaluated while current_validation_job_id IS NULL.
_ADD_COMPOSITE_FK = """
ALTER TABLE import_sessions
    ADD CONSTRAINT fk_import_sessions_current_validation_job
    FOREIGN KEY (id, current_validation_job_id)
    REFERENCES import_jobs (import_session_id, id)
    ON DELETE RESTRICT
"""

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_import_sessions_dataset_type_status "
    "ON import_sessions (dataset_type, status)",
    "CREATE INDEX IF NOT EXISTS ix_import_sessions_created_by_user_id "
    "ON import_sessions (created_by_user_id)",
    "CREATE INDEX IF NOT EXISTS ix_import_sessions_terminal_at ON import_sessions (terminal_at)",
    "CREATE INDEX IF NOT EXISTS ix_import_sessions_retention_cleanup_claim "
    "ON import_sessions (retention_cleanup_claim_expires_at) WHERE retention_purged_at IS NULL",
    # §4.2's Keys/constraints line names exactly `INDEX (checksum)` -- not
    # `source_fingerprint` (PR84-H2). checksum is the column callers and
    # support tooling look records up by.
    "CREATE INDEX IF NOT EXISTS ix_import_sources_checksum ON import_sources (checksum)",
    "CREATE INDEX IF NOT EXISTS ix_import_jobs_session_id_job_type ON import_jobs (import_session_id, job_type)",
    "CREATE INDEX IF NOT EXISTS ix_import_jobs_lease_expires_at "
    "ON import_jobs (lease_expires_at) WHERE status = 'running'",
    "CREATE INDEX IF NOT EXISTS ix_import_row_errors_job_id_row_number "
    "ON import_row_errors (import_job_id, row_number)",
)

_GOVERNED_TABLES = ("import_sessions", "import_sources", "import_jobs", "import_row_errors")

# PR84-H1R: every column this migration governs, across all four tables,
# regardless of which later slice (PR19A2/A3) populates or reads it (§4.6:
# "for every table and every column ... is entirely PR19A1's testing
# responsibility"). Each value is
# (data_type, udt_name, character_maximum_length, is_nullable, column_default)
# exactly as `information_schema.columns` reports it -- captured empirically
# against a real, freshly-installed PostgreSQL 16 database, never
# hand-guessed. `column_default` is PostgreSQL's own catalog rendering of
# the DDL `DEFAULT` clause (e.g. `"'created'::character varying"`, `'now()'`,
# `'0'`) -- `None` means "no server default", which is itself part of the
# contract for nullable columns with no default at all.
_EXPECTED_COLUMNS = {
    "import_sessions": {
        "created_at": ("timestamp with time zone", "timestamptz", None, "NO", "now()"),
        "created_by_user_id": ("uuid", "uuid", None, "NO", None),
        "current_validation_job_id": ("uuid", "uuid", None, "YES", None),
        "dataset_type": ("character varying", "varchar", 100, "NO", None),
        "dry_run_completed_at": ("timestamp with time zone", "timestamptz", None, "YES", None),
        "executed_at": ("timestamp with time zone", "timestamptz", None, "YES", None),
        "failure_reason": ("text", "text", None, "YES", None),
        "id": ("uuid", "uuid", None, "NO", None),
        "idempotency_key": ("character varying", "varchar", 200, "YES", None),
        "imported_rows": ("integer", "int4", None, "YES", None),
        "invalid_rows": ("integer", "int4", None, "YES", None),
        "notes": ("text", "text", None, "YES", None),
        "retention_cleanup_claim_expires_at": ("timestamp with time zone", "timestamptz", None, "YES", None),
        "retention_cleanup_claimed_by": ("uuid", "uuid", None, "YES", None),
        "retention_purged_at": ("timestamp with time zone", "timestamptz", None, "YES", None),
        "source_bytes_deleted_at": ("timestamp with time zone", "timestamptz", None, "YES", None),
        "status": ("character varying", "varchar", 30, "NO", "'created'::character varying"),
        "terminal_at": ("timestamp with time zone", "timestamptz", None, "YES", None),
        "total_rows": ("integer", "int4", None, "YES", None),
        "updated_at": ("timestamp with time zone", "timestamptz", None, "NO", "now()"),
        "valid_rows": ("integer", "int4", None, "YES", None),
        "validated_at": ("timestamp with time zone", "timestamptz", None, "YES", None),
        "version": ("integer", "int4", None, "NO", "0"),
        "warning_rows": ("integer", "int4", None, "YES", None),
    },
    "import_sources": {
        "byte_size": ("bigint", "int8", None, "NO", None),
        "checksum": ("character varying", "varchar", 128, "NO", None),
        "content_type": ("character varying", "varchar", 255, "YES", None),
        "created_at": ("timestamp with time zone", "timestamptz", None, "NO", "now()"),
        "filename": ("character varying", "varchar", 255, "YES", None),
        "frozen_at": ("timestamp with time zone", "timestamptz", None, "YES", None),
        "id": ("uuid", "uuid", None, "NO", None),
        "import_session_id": ("uuid", "uuid", None, "NO", None),
        "options_fingerprint": ("character varying", "varchar", 64, "NO", None),
        "source_fingerprint": ("character varying", "varchar", 64, "NO", None),
        "source_version": ("character varying", "varchar", 100, "YES", None),
        "status": ("character varying", "varchar", 20, "NO", "'registered'::character varying"),
    },
    "import_jobs": {
        "attempt_number": ("integer", "int4", None, "NO", None),
        "created_at": ("timestamp with time zone", "timestamptz", None, "NO", "now()"),
        "error_message": ("text", "text", None, "YES", None),
        "finished_at": ("timestamp with time zone", "timestamptz", None, "YES", None),
        "heartbeat_at": ("timestamp with time zone", "timestamptz", None, "YES", None),
        "id": ("uuid", "uuid", None, "NO", None),
        "import_session_id": ("uuid", "uuid", None, "NO", None),
        "job_type": ("character varying", "varchar", 20, "NO", None),
        "lease_expires_at": ("timestamp with time zone", "timestamptz", None, "YES", None),
        "lease_generation": ("integer", "int4", None, "NO", "1"),
        "lease_owner": ("uuid", "uuid", None, "YES", None),
        "ruleset_version": ("character varying", "varchar", 50, "YES", None),
        "started_at": ("timestamp with time zone", "timestamptz", None, "YES", None),
        "status": ("character varying", "varchar", 20, "NO", "'pending'::character varying"),
    },
    "import_row_errors": {
        "error_code": ("character varying", "varchar", 100, "NO", None),
        "field": ("character varying", "varchar", 100, "YES", None),
        "id": ("uuid", "uuid", None, "NO", None),
        "import_job_id": ("uuid", "uuid", None, "NO", None),
        "message": ("text", "text", None, "NO", None),
        "row_number": ("integer", "int4", None, "YES", None),
        "severity": ("character varying", "varchar", 10, "NO", "'error'::character varying"),
    },
}

# Every constraint (PK/FK/UNIQUE/CHECK) on the four governed tables --
# `pg_get_constraintdef()` renders all four kinds uniformly, so one
# classification path covers them all, including PostgreSQL's own
# auto-generated FK/PK constraint names. Captured empirically the same way
# as `_EXPECTED_COLUMNS`. This supersedes the CHECK-only `_EXPECTED_CHECK_
# DEFS` this migration originally shipped with (PR84-H1R) -- the CHECK
# entries below are unchanged from that version.
_EXPECTED_CONSTRAINTS = {
    "import_sessions": {
        "ck_import_sessions_failure_reason_length": "CHECK ((length(failure_reason) <= 2000))",
        "ck_import_sessions_notes_length": "CHECK ((length(notes) <= 4000))",
        "ck_import_sessions_status": (
            "CHECK (((status)::text = ANY ((ARRAY["
            "'created'::character varying, 'validating'::character varying, 'validated'::character varying, "
            "'validation_failed'::character varying, 'dry_run_running'::character varying, "
            "'dry_run_completed'::character varying, 'dry_run_failed'::character varying, "
            "'executing'::character varying, 'completed'::character varying, 'failed'::character varying, "
            "'cancelled'::character varying])::text[])))"
        ),
        "fk_import_sessions_current_validation_job": (
            "FOREIGN KEY (id, current_validation_job_id) REFERENCES import_jobs(import_session_id, id) "
            "ON DELETE RESTRICT"
        ),
        "import_sessions_created_by_user_id_fkey": "FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT",
        "import_sessions_pkey": "PRIMARY KEY (id)",
        "uq_import_sessions_dataset_idempotency": "UNIQUE (dataset_type, idempotency_key)",
    },
    "import_sources": {
        "ck_import_sources_checksum_length": "CHECK ((length((checksum)::text) >= 32))",
        "ck_import_sources_status": (
            "CHECK (((status)::text = ANY ((ARRAY['registered'::character varying, "
            "'frozen'::character varying])::text[])))"
        ),
        "import_sources_import_session_id_fkey": "FOREIGN KEY (import_session_id) REFERENCES import_sessions(id) ON DELETE RESTRICT",
        "import_sources_import_session_id_key": "UNIQUE (import_session_id)",
        "import_sources_pkey": "PRIMARY KEY (id)",
    },
    "import_jobs": {
        "ck_import_jobs_error_message_length": "CHECK ((length(error_message) <= 2000))",
        "ck_import_jobs_job_type": (
            "CHECK (((job_type)::text = ANY ((ARRAY['validate'::character varying, "
            "'dry_run'::character varying, 'execute'::character varying])::text[])))"
        ),
        "ck_import_jobs_status": (
            "CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying, "
            "'succeeded'::character varying, 'failed'::character varying, "
            "'abandoned'::character varying])::text[])))"
        ),
        "import_jobs_import_session_id_fkey": "FOREIGN KEY (import_session_id) REFERENCES import_sessions(id) ON DELETE RESTRICT",
        "import_jobs_pkey": "PRIMARY KEY (id)",
        "uq_import_jobs_session_id": "UNIQUE (import_session_id, id)",
        "uq_import_jobs_session_job_type_attempt": "UNIQUE (import_session_id, job_type, attempt_number)",
    },
    "import_row_errors": {
        "ck_import_row_errors_severity": (
            "CHECK (((severity)::text = ANY ((ARRAY['error'::character varying, "
            "'warning'::character varying])::text[])))"
        ),
        "import_row_errors_import_job_id_fkey": "FOREIGN KEY (import_job_id) REFERENCES import_jobs(id) ON DELETE RESTRICT",
        "import_row_errors_pkey": "PRIMARY KEY (id)",
    },
}

# Every index on the four governed tables (PK-backing, UNIQUE-backing, and
# plain), captured the same way. `indexdef` alone is not sufficient for
# compatibility -- see `_classify_index()`'s health check below.
_EXPECTED_INDEXES = {
    "import_sessions": {
        "import_sessions_pkey": "CREATE UNIQUE INDEX import_sessions_pkey ON public.import_sessions USING btree (id)",
        "ix_import_sessions_created_by_user_id": (
            "CREATE INDEX ix_import_sessions_created_by_user_id ON public.import_sessions USING btree "
            "(created_by_user_id)"
        ),
        "ix_import_sessions_dataset_type_status": (
            "CREATE INDEX ix_import_sessions_dataset_type_status ON public.import_sessions USING btree "
            "(dataset_type, status)"
        ),
        "ix_import_sessions_retention_cleanup_claim": (
            "CREATE INDEX ix_import_sessions_retention_cleanup_claim ON public.import_sessions USING btree "
            "(retention_cleanup_claim_expires_at) WHERE (retention_purged_at IS NULL)"
        ),
        "ix_import_sessions_terminal_at": "CREATE INDEX ix_import_sessions_terminal_at ON public.import_sessions USING btree (terminal_at)",
        "uq_import_sessions_dataset_idempotency": (
            "CREATE UNIQUE INDEX uq_import_sessions_dataset_idempotency ON public.import_sessions USING btree "
            "(dataset_type, idempotency_key)"
        ),
    },
    "import_sources": {
        "import_sources_import_session_id_key": (
            "CREATE UNIQUE INDEX import_sources_import_session_id_key ON public.import_sources USING btree "
            "(import_session_id)"
        ),
        "import_sources_pkey": "CREATE UNIQUE INDEX import_sources_pkey ON public.import_sources USING btree (id)",
        "ix_import_sources_checksum": "CREATE INDEX ix_import_sources_checksum ON public.import_sources USING btree (checksum)",
    },
    "import_jobs": {
        "import_jobs_pkey": "CREATE UNIQUE INDEX import_jobs_pkey ON public.import_jobs USING btree (id)",
        "ix_import_jobs_lease_expires_at": (
            "CREATE INDEX ix_import_jobs_lease_expires_at ON public.import_jobs USING btree (lease_expires_at) "
            "WHERE ((status)::text = 'running'::text)"
        ),
        "ix_import_jobs_session_id_job_type": (
            "CREATE INDEX ix_import_jobs_session_id_job_type ON public.import_jobs USING btree "
            "(import_session_id, job_type)"
        ),
        "uq_import_jobs_session_id": (
            "CREATE UNIQUE INDEX uq_import_jobs_session_id ON public.import_jobs USING btree "
            "(import_session_id, id)"
        ),
        "uq_import_jobs_session_job_type_attempt": (
            "CREATE UNIQUE INDEX uq_import_jobs_session_job_type_attempt ON public.import_jobs USING btree "
            "(import_session_id, job_type, attempt_number)"
        ),
    },
    "import_row_errors": {
        "import_row_errors_pkey": "CREATE UNIQUE INDEX import_row_errors_pkey ON public.import_row_errors USING btree (id)",
        "ix_import_row_errors_job_id_row_number": (
            "CREATE INDEX ix_import_row_errors_job_id_row_number ON public.import_row_errors USING btree "
            "(import_job_id, row_number)"
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
# PR84-H1R3: relation-scoped by construction -- PostgreSQL constraint names
# are unique only *within* a relation, not schema- or database-wide (unlike
# index names, which `_INDEX_ROW_SQL` below correctly scopes only by
# schema+name for exactly that reason). A bare `WHERE conname = :name`
# would match a same-named constraint on any other table, silently
# classifying the *target* table as compatible even when it never had this
# constraint at all. `conrelid = (:t)::regclass` makes an unscoped lookup
# impossible by construction -- every caller must supply the owning table.
# Also fetches `convalidated`: a CHECK/FK constraint can exist, matching
# name and definition, and still be `NOT VALID` (e.g. an interrupted
# `ADD CONSTRAINT ... NOT VALID` + deferred `VALIDATE CONSTRAINT`) -- never
# classified as compatible in that state, mirroring the index health gate.
_CONSTRAINT_DEF_SQL = sa.text(
    "SELECT pg_get_constraintdef(oid), convalidated FROM pg_constraint "
    "WHERE conrelid = (:t)::regclass AND conname = :name"
)
# Mirrors migration 0014's `_INDEX_ROW_SQL` -- the same join pattern this
# codebase already established for "index definition + health in one query".
_INDEX_ROW_SQL = sa.text(
    """
    SELECT ix.indexdef, i.indisvalid, i.indisready
    FROM pg_indexes ix
    JOIN pg_class c ON c.relname = ix.indexname AND c.relnamespace = 'public'::regnamespace
    JOIN pg_index i ON i.indexrelid = c.oid
    WHERE ix.schemaname = 'public' AND ix.indexname = :name
    """
)

# PR84-H1R2: closed-world governed-set queries -- every actual column /
# constraint / index name PostgreSQL reports for a table, used to detect
# objects that exist but are *not* in `_EXPECTED_*` at all (§4's physical
# schema contract is exact: `expected_governed_objects == actual_governed_
# objects`, not `expected ⊆ actual`). Boundary, explicitly: `contype IN
# ('p','f','u','c')` is every constraint kind this design ever declares
# (PRIMARY KEY/FOREIGN KEY/UNIQUE/CHECK) -- this schema has no EXCLUDE
# constraints, so 'x' is deliberately outside the governed set; nothing
# else in `pg_constraint` is table-scoped in a way that could collide here.
# `pg_indexes` already lists exactly the application-visible indexes for a
# table -- both plain indexes and the indexes PostgreSQL auto-creates to
# back a PRIMARY KEY/UNIQUE constraint (e.g. `import_sessions_pkey`,
# `import_sources_import_session_id_key`) -- no TOAST/internal objects.
# `_EXPECTED_INDEXES` already lists every one of those backing indexes by
# its real PostgreSQL-assigned name (captured empirically, same as every
# other expected value here), so no special-casing is needed to tell a
# "real" index apart from a constraint-backing one: both are first-class
# entries in the same dict, and any index name present in the catalog but
# absent from `_EXPECTED_INDEXES[table]` is, by construction, an unexpected
# governed object.
_ACTUAL_COLUMN_NAMES_SQL = sa.text(
    "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :t"
)
_ACTUAL_CONSTRAINT_NAMES_SQL = sa.text(
    "SELECT conname FROM pg_constraint WHERE conrelid = (:t)::regclass AND contype IN ('p', 'f', 'u', 'c')"
)
_ACTUAL_INDEX_NAMES_SQL = sa.text(
    "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = :t"
)


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
    """`table` is required, not optional -- there is no code path in this
    module that can look up a constraint without naming the relation it
    must belong to (PR84-H1R3)."""
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
    # PR84-H1R: a same-named, same-defined index is still not usable if it
    # is not valid/ready (e.g. left behind by an interrupted CREATE INDEX
    # CONCURRENTLY) -- health is an independent, required gate, exactly as
    # migration 0014 already established for its own governed indexes.
    if not (row.indisvalid and row.indisready):
        return _INCOMPATIBLE_HEALTH, (row.indexdef, row.indisvalid, row.indisready)
    return _COMPATIBLE, (row.indexdef, row.indisvalid, row.indisready)


def _verify_schema_convergence(bind) -> None:
    """PR84-H1R/H1R2: production, migration-owned fail-closed catalog
    classification -- not merely CHECK-constraint text, and not only
    enforced by the test suite. Runs after every CREATE/ALTER statement in
    `upgrade()` above, so it classifies the schema's *actual final state*,
    whichever path produced it: freshly created by this migration's own
    `IF NOT EXISTS` DDL, already present and correct from the ORM
    fresh-install path, or a genuinely incompatible pre-existing historical
    object that `IF NOT EXISTS` silently no-op'd against.

    The required invariant is `expected_governed_objects ==
    actual_governed_objects` -- exact closed-world equality, not merely
    `expected ⊆ actual`. §4's physical schema contract is exact: an
    unexpected same-table object (e.g. an additional `UNIQUE(checksum)` on
    `import_sources`) changes write behavior even though every *expected*
    object is still present and correct, so it must fail closed exactly
    like a wrong-definition or unhealthy expected object would. Every
    governed column/constraint/index across all four tables is classified
    MISSING / COMPATIBLE / INCOMPATIBLE (wrong definition, unhealthy, or
    -- new here -- present but not part of the design contract at all). A
    MISSING classification means this migration's own preceding CREATE
    statement did not produce the object -- an internal migration bug,
    never a pre-existing-schema case, since MISSING is only checked after
    creation has already run. Any non-COMPATIBLE classification aborts the
    migration with every mismatch it found, described concretely (table,
    object, expected value, actual value) -- never a bare assertion, and
    never a partial fix (drop/rename/rebuild/coerce) applied on its own
    initiative. Because every `op.execute()` call in `upgrade()` runs
    inside Alembic's single per-invocation transaction (`alembic/env.py`'s
    `context.begin_transaction()`), raising here rolls back every DDL
    statement this migration issued *and* Alembic's own `alembic_version`
    bookkeeping update together -- a failed run leaves the pre-migration
    schema, including the object that caused the failure, completely
    unchanged (proven by `test_migration_0015_failed_verification_leaves_no_
    partial_state_and_does_not_advance_alembic_version`).
    """
    problems: list[str] = []

    for table in _GOVERNED_TABLES:
        unexpected_columns = _unexpected_object_names(
            bind, _ACTUAL_COLUMN_NAMES_SQL, table, _EXPECTED_COLUMNS[table]
        )
        if unexpected_columns:
            problems.append(
                f"{table}: unexpected column(s) not part of the PR19A1 design contract "
                f"(docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md §4): {sorted(unexpected_columns)}. "
                "An extra application column is never silently accepted merely because every expected "
                "column also exists."
            )
        unexpected_constraints = _unexpected_object_names(
            bind, _ACTUAL_CONSTRAINT_NAMES_SQL, table, _EXPECTED_CONSTRAINTS[table]
        )
        if unexpected_constraints:
            problems.append(
                f"{table}: unexpected constraint(s) (PRIMARY KEY/FOREIGN KEY/UNIQUE/CHECK) not part of "
                f"the PR19A1 design contract: {sorted(unexpected_constraints)}. An extra constraint (e.g. "
                "an additional UNIQUE) changes write behavior even when every expected constraint is "
                "also present and correct -- never silently accepted."
            )
        unexpected_indexes = _unexpected_object_names(bind, _ACTUAL_INDEX_NAMES_SQL, table, _EXPECTED_INDEXES[table])
        if unexpected_indexes:
            problems.append(
                f"{table}: unexpected index(es) not part of the PR19A1 design contract: "
                f"{sorted(unexpected_indexes)}. `_EXPECTED_INDEXES` already lists every index this design "
                "requires, including the ones PostgreSQL auto-creates to back a PRIMARY KEY/UNIQUE "
                "constraint -- any index name outside that set is an unexpected governed object."
            )

    for table, columns in _EXPECTED_COLUMNS.items():
        for column, expected in columns.items():
            kind, actual = _classify_column(bind, table, column, expected)
            if kind == _MISSING:
                problems.append(
                    f"{table}.{column}: column does not exist even after this migration's own CREATE "
                    "TABLE ran -- this indicates an internal migration bug, not a pre-existing "
                    "incompatible schema."
                )
            elif kind == _INCOMPATIBLE_DEFINITION:
                problems.append(
                    f"{table}.{column}: column exists but diverges from the design contract "
                    "(docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md §4).\n"
                    f"    Expected (data_type, udt_name, char_max_length, is_nullable, column_default) = "
                    f"{expected!r}\n"
                    f"    Actual                                                                        = "
                    f"{actual!r}"
                )

    for table, constraints in _EXPECTED_CONSTRAINTS.items():
        for name, expected_def in constraints.items():
            # PR84-H1R3: `expected_constraint_names - actual_constraint_names`
            # for this table, computed one name at a time -- `_classify_
            # constraint` looks up `name` scoped to exactly `table` via
            # `conrelid`, so MISSING here can only mean "not owned by this
            # relation", never "exists somewhere else in the database under
            # the same name." A same-named constraint on another table (or
            # in another schema) never satisfies this lookup and is
            # therefore correctly invisible to it.
            kind, actual = _classify_constraint(bind, table, name, expected_def)
            if kind == _MISSING:
                problems.append(
                    f"{table}: constraint '{name}' does not exist on this table even after this "
                    "migration's own DDL ran -- this indicates an internal migration bug, not a "
                    "pre-existing incompatible schema. (A same-named constraint on a different table "
                    "would never satisfy this relation-scoped check.)"
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
                    f"validated (pg_constraint.convalidated={validated}). This usually means a "
                    "previous `ADD CONSTRAINT ... NOT VALID` was never followed by `VALIDATE "
                    "CONSTRAINT`. A same-named, same-definition constraint is never classified as "
                    "compatible while unvalidated."
                )

    for table, indexes in _EXPECTED_INDEXES.items():
        for name, expected_def in indexes.items():
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
                    f"{table}: index '{name}' exists but its definition diverges (CREATE INDEX IF NOT "
                    "EXISTS silently no-ops against a same-named index regardless of its actual "
                    "definition -- name equality alone is never treated as compatibility).\n"
                    f"    Expected: {expected_def}\n"
                    f"    Actual:   {actual_def}"
                )
            elif kind == _INCOMPATIBLE_HEALTH:
                actual_def, valid, ready = actual
                problems.append(
                    f"{table}: index '{name}' matches its expected definition but is not usable "
                    f"(pg_index.indisvalid={valid}, indisready={ready}). This usually means a previous "
                    "CREATE INDEX CONCURRENTLY / REINDEX CONCURRENTLY was interrupted. A same-named, "
                    "same-definition index is never classified as compatible while unhealthy."
                )

    if problems:
        raise RuntimeError(
            "Migration 0015 aborted: the existing PostgreSQL catalog diverges from the PR19A1 design "
            f"contract (docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md §4/§4.6) in {len(problems)} "
            "way(s). Refusing to silently continue with an incompatible historical schema:\n\n"
            + "\n\n".join(problems)
        )


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    # import_sessions has no forward reference to import_jobs at creation
    # time (the composite FK is added after both tables exist, below).
    op.execute(sa.text(_CREATE_IMPORT_SESSIONS))
    op.execute(sa.text(_CREATE_IMPORT_SOURCES))
    op.execute(sa.text(_CREATE_IMPORT_JOBS))
    op.execute(sa.text(_CREATE_IMPORT_ROW_ERRORS))

    # Idempotent: only add the composite FK if it does not already exist
    # (the fresh-install path already created it via ORM metadata).
    # PR84-H1R3: scoped by conrelid -- a same-named constraint elsewhere
    # must never be mistaken for import_sessions already having its own
    # composite ownership FK (which would wrongly skip creating it here).
    existing_fk = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_constraint WHERE conrelid = 'import_sessions'::regclass "
            "AND conname = 'fk_import_sessions_current_validation_job'"
        )
    ).one_or_none()
    if existing_fk is None:
        op.execute(sa.text(_ADD_COMPOSITE_FK))

    for stmt in _INDEXES:
        op.execute(sa.text(stmt))

    _verify_schema_convergence(bind)


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    # FK-dependency order: import_sessions' composite FK references
    # import_jobs, so drop that constraint (implicitly, via the table drop
    # order below) before import_jobs itself. import_row_errors references
    # import_jobs; import_jobs and import_sources reference import_sessions.
    op.execute(sa.text("ALTER TABLE import_sessions DROP CONSTRAINT IF EXISTS fk_import_sessions_current_validation_job"))
    op.execute(sa.text("DROP TABLE IF EXISTS import_row_errors"))
    op.execute(sa.text("DROP TABLE IF EXISTS import_jobs"))
    op.execute(sa.text("DROP TABLE IF EXISTS import_sources"))
    op.execute(sa.text("DROP TABLE IF EXISTS import_sessions"))
