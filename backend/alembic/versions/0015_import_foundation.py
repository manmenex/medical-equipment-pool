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
all four tables -- with their exact, explicitly-named `CheckConstraint`s
(§4's "every enum-shaped column is a plain VARCHAR with a named CHECK
constraint", enforced here via literal `CheckConstraint(name=...)` objects
on each model, not SQLAlchemy's `Enum` type) -- on any database that runs
`0001` against the *current* model set, i.e. any brand-new install. This
migration's own raw SQL below is what creates these tables on a database
that already historically applied `0001`-`0014` *before* this slice existed
(the only path where `0001`'s `create_all()` could not have created them).
`CREATE TABLE IF NOT EXISTS` makes the fresh-install path's re-application
of this migration a no-op; the verification step below then confirms both
paths converge to identical CHECK-constraint definitions, failing closed
(not silently continuing) if a same-named table already exists with a
different shape than expected -- the same "verify, don't just no-op"
discipline migrations 0013/0014 established.

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
    CONSTRAINT uq_import_sessions_dataset_idempotency UNIQUE (dataset_type, idempotency_key)
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
    CONSTRAINT uq_import_jobs_session_job_type_attempt UNIQUE (import_session_id, job_type, attempt_number)
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
    "CREATE INDEX IF NOT EXISTS ix_import_sources_source_fingerprint ON import_sources (source_fingerprint)",
    "CREATE INDEX IF NOT EXISTS ix_import_jobs_session_id_job_type ON import_jobs (import_session_id, job_type)",
    "CREATE INDEX IF NOT EXISTS ix_import_jobs_lease_expires_at "
    "ON import_jobs (lease_expires_at) WHERE status = 'running'",
    "CREATE INDEX IF NOT EXISTS ix_import_row_errors_job_id_row_number "
    "ON import_row_errors (import_job_id, row_number)",
)

# §8 acceptance criteria: after either path (fresh-install no-op, or this
# migration's own CREATE TABLE), the named CHECK constraint on each table
# must exist with exactly this canonical definition -- verified here so a
# divergence (e.g. the H2 defect from the original PR19A review: an ORM
# Enum without create_constraint, silently producing no constraint at all
# on the fresh path) fails this migration closed instead of shipping a
# silent schema drift.
_EXPECTED_CHECK_DEFS = {
    "ck_import_sessions_status": (
        "CHECK (((status)::text = ANY ((ARRAY["
        "'created'::character varying, 'validating'::character varying, 'validated'::character varying, "
        "'validation_failed'::character varying, 'dry_run_running'::character varying, "
        "'dry_run_completed'::character varying, 'dry_run_failed'::character varying, "
        "'executing'::character varying, 'completed'::character varying, 'failed'::character varying, "
        "'cancelled'::character varying])::text[])))"
    ),
    "ck_import_sources_status": (
        "CHECK (((status)::text = ANY ((ARRAY['registered'::character varying, "
        "'frozen'::character varying])::text[])))"
    ),
    "ck_import_sources_checksum_length": "CHECK ((length((checksum)::text) >= 32))",
    "ck_import_jobs_job_type": (
        "CHECK (((job_type)::text = ANY ((ARRAY['validate'::character varying, "
        "'dry_run'::character varying, 'execute'::character varying])::text[])))"
    ),
    "ck_import_jobs_status": (
        "CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying, "
        "'succeeded'::character varying, 'failed'::character varying, "
        "'abandoned'::character varying])::text[])))"
    ),
    "ck_import_row_errors_severity": (
        "CHECK (((severity)::text = ANY ((ARRAY['error'::character varying, "
        "'warning'::character varying])::text[])))"
    ),
}

_CONSTRAINT_DEF_SQL = sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :name")


def _verify_check_constraints(bind) -> None:
    for name, expected in _EXPECTED_CHECK_DEFS.items():
        row = bind.execute(_CONSTRAINT_DEF_SQL, {"name": name}).one_or_none()
        if row is None:
            raise RuntimeError(
                f"Migration 0015 aborted: expected CHECK constraint '{name}' does not exist after "
                "table creation on either the fresh-install or historical-upgrade path. Refusing to "
                "continue with a schema that would silently accept out-of-domain values."
            )
        actual = row[0]
        if actual != expected:
            raise RuntimeError(
                f"Migration 0015 aborted: CHECK constraint '{name}' exists but its definition diverges "
                f"between the fresh-install and historical-upgrade paths.\nExpected: {expected}\n"
                f"Actual:   {actual}\nThis is the exact class of divergence Roadmap PR19A1 (§8) exists "
                "to prevent -- refusing to silently continue with two databases that enforce different "
                "domains for the same column."
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
    existing_fk = bind.execute(
        sa.text("SELECT 1 FROM pg_constraint WHERE conname = 'fk_import_sessions_current_validation_job'")
    ).one_or_none()
    if existing_fk is None:
        op.execute(sa.text(_ADD_COMPOSITE_FK))

    for stmt in _INDEXES:
        op.execute(sa.text(stmt))

    _verify_check_constraints(bind)


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
