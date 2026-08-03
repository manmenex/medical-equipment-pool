"""add import_sessions, import_jobs, import_row_errors (Roadmap PR19A)

Revision ID: 0015_import_foundation
Revises: 0014_index_naming_convergence
Create Date: 2026-08-03

Roadmap PR19A (docs/audits/04-consolidated-implementation-plan.md Part D
"PR19 -- Legacy Import Foundation"; docs/design/
PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md): three new, purely additive tables
that back the staged, validation-first, traceable import framework
described in app.models.import_session / app.services.import_foundation.

  - import_sessions   one row per staged import attempt for one dataset
                       type (design §3). No column here references, and
                       no application code in this slice ever writes to,
                       `equipment`, `borrow_transactions`, or any other
                       existing domain table -- this migration cannot
                       affect any existing behavior.
  - import_jobs        one row per phase (validate / dry_run / execute) of
                       an import session (design §7, "resumable import
                       sessions -- foundation only").
  - import_row_errors  one row per collected validation/business-rule
                       failure (design §6, "Error collection model").

Every enum-shaped column (`import_sessions.status`, `import_jobs.job_type`/
`.status`, `import_row_errors.severity`) is a plain bounded VARCHAR with a
CHECK constraint, not a native PostgreSQL enum type -- same convention
`app.models.equipment.EquipmentStatusType` already established, chosen so a
future added state never requires a `ALTER TYPE ... ADD VALUE` migration.

All three new foreign keys (`import_sessions.created_by_user_id`,
`import_jobs.import_session_id`, `import_row_errors.import_session_id`) are
`ON DELETE RESTRICT`, extending Roadmap PR15B's (migration
0013_fk_ondelete_policy) explicit "every foreign key is RESTRICT, never
CASCADE" policy to this new schema -- no code path in this slice performs a
real SQL DELETE against any of these three tables, so this is a zero-cost
consistency choice, not a functional one (`tests/test_postgres_integration.
py::test_migration_0013_fresh_database_all_25_foreign_keys_are_restrict`
now expects 28, not 25, foreign keys at head, all RESTRICT).

This migration follows the identical PostgreSQL-only-via-raw-SQL,
`IF NOT EXISTS`-idempotent shape as migrations 0009/0010: the SQLite
test/dev path builds its schema directly from
`app.models.import_session`'s ORM definitions via `Base.metadata.
create_all()`, so nothing here needs to (or may) run there. This migration
does NOT import any `app.models`/`app.services` runtime module (0005-0014's
established convention) -- every column definition and constraint name
below is frozen locally at this revision, independent of any future change
to the ORM models.

Downgrade: drops all three tables (in FK-dependency order: import_row_errors
and import_jobs before import_sessions). Fully reversible with no data-loss
concern for any *other* table, since nothing outside these three tables
ever references them -- but downgrading after a real import session has
been created, validated, dry-run, or executed permanently discards that
session's own history (its `ImportJob`/`ImportRowError` audit trail). A
forward fix is preferred over downgrading a database that has real import
sessions on it, consistent with this project's general migration
philosophy (Part E, "additive-first").
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0015_import_foundation"
down_revision: Union[str, None] = "0014_index_naming_convergence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SESSION_STATUSES = (
    "created",
    "validating",
    "validated",
    "validation_failed",
    "dry_run_running",
    "dry_run_completed",
    "dry_run_failed",
    "executing",
    "completed",
    "failed",
    "cancelled",
)
_JOB_TYPES = ("validate", "dry_run", "execute")
_JOB_STATUSES = ("pending", "running", "succeeded", "failed")
_ERROR_SEVERITIES = ("error", "warning")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        # Migrations only ever run against PostgreSQL in this project (see
        # 0002-0014's identical branch) -- the SQLite test/dev path builds
        # its schema via Base.metadata.create_all() directly from the ORM
        # models, which already declare these three tables.
        return

    op.execute(
        "CREATE TABLE IF NOT EXISTS import_sessions ("
        "id UUID PRIMARY KEY, "
        "dataset_type VARCHAR(100) NOT NULL, "
        f"status VARCHAR(30) NOT NULL DEFAULT 'created' "
        f"CONSTRAINT ck_import_sessions_status CHECK (status IN ({_quoted(_SESSION_STATUSES)})), "
        "created_by_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT, "
        "idempotency_key VARCHAR(200), "
        "source_checksum VARCHAR(128), "
        "source_filename VARCHAR(255), "
        "notes TEXT, "
        "validated_at TIMESTAMPTZ, "
        "dry_run_completed_at TIMESTAMPTZ, "
        "executed_at TIMESTAMPTZ, "
        "total_rows INTEGER, "
        "valid_rows INTEGER, "
        "invalid_rows INTEGER, "
        "imported_rows INTEGER, "
        "failure_reason TEXT, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
        "updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
        "CONSTRAINT uq_import_sessions_dataset_idempotency_key UNIQUE (dataset_type, idempotency_key)"
        ")"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_import_sessions_dataset_type ON import_sessions (dataset_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_import_sessions_created_by_user_id ON import_sessions (created_by_user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_import_sessions_dataset_type_status "
        "ON import_sessions (dataset_type, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_import_sessions_source_checksum ON import_sessions (source_checksum)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_import_sessions_created_at ON import_sessions (created_at)"
    )

    op.execute(
        "CREATE TABLE IF NOT EXISTS import_jobs ("
        "id UUID PRIMARY KEY, "
        "import_session_id UUID NOT NULL REFERENCES import_sessions(id) ON DELETE RESTRICT, "
        "job_type VARCHAR(20) NOT NULL "
        f"CONSTRAINT ck_import_jobs_job_type CHECK (job_type IN ({_quoted(_JOB_TYPES)})), "
        f"status VARCHAR(20) NOT NULL DEFAULT 'pending' "
        f"CONSTRAINT ck_import_jobs_status CHECK (status IN ({_quoted(_JOB_STATUSES)})), "
        "started_at TIMESTAMPTZ, "
        "finished_at TIMESTAMPTZ, "
        "error_message TEXT, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
        "updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"
        ")"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_import_jobs_import_session_id ON import_jobs (import_session_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_import_jobs_session_id_job_type "
        "ON import_jobs (import_session_id, job_type)"
    )

    op.execute(
        "CREATE TABLE IF NOT EXISTS import_row_errors ("
        "id UUID PRIMARY KEY, "
        "import_session_id UUID NOT NULL REFERENCES import_sessions(id) ON DELETE RESTRICT, "
        "row_number INTEGER, "
        "field VARCHAR(100), "
        "error_code VARCHAR(100) NOT NULL, "
        "message TEXT NOT NULL, "
        f"severity VARCHAR(10) NOT NULL DEFAULT 'error' "
        f"CONSTRAINT ck_import_row_errors_severity CHECK (severity IN ({_quoted(_ERROR_SEVERITIES)}))"
        ")"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_import_row_errors_import_session_id ON import_row_errors (import_session_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_import_row_errors_session_id_row_number "
        "ON import_row_errors (import_session_id, row_number)"
    )


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP TABLE IF EXISTS import_row_errors")
    op.execute("DROP TABLE IF EXISTS import_jobs")
    op.execute("DROP TABLE IF EXISTS import_sessions")
