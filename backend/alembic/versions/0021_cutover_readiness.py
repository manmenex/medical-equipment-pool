"""Roadmap PR23B -- Cutover Readiness Evidence Foundation

Revision ID: 0021_cutover_readiness
Revises: 0020_reconciliation_foundation
Create Date: 2026-08-25

Roadmap PR23B (docs/design/PR23_CUTOVER_READINESS_PLAN.md §9, §10, §11,
§12 Gate D/E, §15, §16, §26 -- OD-PR23-1 through OD-PR23-6, all
RESOLVED / OWNER APPROVED via the PR23 Owner Decision Closure round),
refined by the PR23B implementation task's own binding field contract.
Introduces one new, purely additive table: `cutover_readiness_runs` --
one cutover-readiness evidence-capture attempt per row, referencing (by
id, never duplicating) PR20's `ImportSource`, PR21's
`LegacyMigrationAuthority`, PR22's `LegacyMigrationAuthorityCoverage`/
`LegacyReconciliationRun`/`LegacyReconciliationSignOff`, and `Ward`;
`pending`/`running`/`completed`/`failed` lifecycle (no `approved`/`go`/
`no_go`/`cutover_complete`/`rolled_back` value -- Go/No-Go semantics
belong to a later PR23 slice); forward-only supersession via
`supersedes_run_id`, mirroring `LegacyReconciliationRun`'s own
OD-PR22-3 discipline. No existing table is modified. This slice
implements no readiness-gate evaluation (PR23C), no Go/No-Go decision/
sign-off logic (PR23D), and no frontend (PR23E).

**Fresh-install vs. historical-upgrade convergence**, following the
exact discipline migrations `0015`-`0020` established (see those
migrations' own extensive docstrings for the full rationale -- not
restated here). `app.models.cutover_readiness` (registered in
`app/db/base.py`) already defines the ORM model, so `0001_initial.py`'s
`Base.metadata.create_all()` already creates this table on any
brand-new install. This migration's own raw SQL is what creates it on
a database that historically applied `0001`-`0020` before this slice
existed. `_verify_schema_convergence()` below is the same
production-owned, fail-closed catalog classification pattern as
`0015`-`0020`'s (closed-world column/constraint/index equality,
index/constraint health gates, relation-scoped constraint lookups) --
every expected value captured empirically against a real, freshly
migrated PostgreSQL 16 database (this repository's own local instance,
migrated through `0020` first, then this table created directly via
`Base.metadata.create_all()` and its own catalog rows read back), never
hand-guessed. No auto-generated foreign-key constraint name on this
table is truncated by PostgreSQL's own NAMEDATALEN(63) limit -- every
FK name below is exactly as PostgreSQL generated it.

Only ever runs raw SQL against PostgreSQL (see 0002/0004/0011-0020's
identical dialect-gated pattern) -- SQLite tests create this table via
`Base.metadata.create_all()` directly (`tests/conftest.py`), never via
this migration chain, so ORM model correctness alone is authoritative
there.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021_cutover_readiness"
down_revision: Union[str, None] = "0020_reconciliation_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CREATE_RUNS = """
CREATE TABLE IF NOT EXISTS cutover_readiness_runs (
    id UUID NOT NULL PRIMARY KEY,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    version INTEGER NOT NULL DEFAULT 0,
    created_by_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    completed_at TIMESTAMP WITH TIME ZONE,
    completed_by_user_id UUID REFERENCES users(id) ON DELETE RESTRICT,
    application_baseline_sha VARCHAR(40) NOT NULL,
    database_migration_head VARCHAR(255) NOT NULL,
    source_of_truth_strategy VARCHAR(30) NOT NULL DEFAULT 'hard_cutover',
    cutover_instant TIMESTAMP WITH TIME ZONE NOT NULL,
    freeze_window_reference VARCHAR(255),
    equipment_master_import_source_id UUID REFERENCES import_sources(id) ON DELETE RESTRICT,
    legacy_migration_authority_id UUID REFERENCES legacy_migration_authorities(id) ON DELETE RESTRICT,
    legacy_coverage_id UUID REFERENCES legacy_migration_authority_coverages(id) ON DELETE RESTRICT,
    reconciliation_run_id UUID REFERENCES legacy_reconciliation_runs(id) ON DELETE RESTRICT,
    reconciliation_signoff_id UUID REFERENCES legacy_reconciliation_signoffs(id) ON DELETE RESTRICT,
    current_state_verified_at TIMESTAMP WITH TIME ZONE,
    current_state_verified_by_user_id UUID REFERENCES users(id) ON DELETE RESTRICT,
    current_state_verification_scope_count INTEGER,
    current_state_verification_reference VARCHAR(255),
    pilot_ward_id UUID REFERENCES wards(id) ON DELETE RESTRICT,
    operational_approver_reference VARCHAR(255),
    supersedes_run_id UUID REFERENCES cutover_readiness_runs(id) ON DELETE RESTRICT,
    CONSTRAINT ck_cutover_readiness_runs_status
        CHECK (status IN ('pending','running','completed','failed')),
    CONSTRAINT ck_cutover_readiness_runs_version CHECK (version >= 0),
    CONSTRAINT ck_cutover_readiness_runs_source_of_truth_strategy
        CHECK (source_of_truth_strategy IN ('hard_cutover')),
    CONSTRAINT ck_cutover_readiness_runs_baseline_sha_length
        CHECK (LENGTH(application_baseline_sha) = 40),
    CONSTRAINT ck_cutover_readiness_runs_completed_pair
        CHECK ((completed_at IS NULL) = (completed_by_user_id IS NULL)),
    CONSTRAINT ck_cutover_readiness_runs_verification_pair
        CHECK ((current_state_verified_at IS NULL) = (current_state_verified_by_user_id IS NULL)),
    CONSTRAINT ck_cutover_readiness_runs_verification_scope_nonneg
        CHECK (current_state_verification_scope_count IS NULL OR current_state_verification_scope_count >= 0),
    CONSTRAINT ck_cutover_readiness_runs_no_self_supersession
        CHECK (supersedes_run_id IS NULL OR supersedes_run_id <> id),
    CONSTRAINT ck_cutover_readiness_runs_completion_requires_evidence
        CHECK (status <> 'completed' OR (
            equipment_master_import_source_id IS NOT NULL AND
            legacy_migration_authority_id IS NOT NULL AND
            legacy_coverage_id IS NOT NULL AND
            reconciliation_run_id IS NOT NULL AND
            reconciliation_signoff_id IS NOT NULL AND
            current_state_verified_at IS NOT NULL AND
            current_state_verified_by_user_id IS NOT NULL AND
            completed_at IS NOT NULL AND
            completed_by_user_id IS NOT NULL
        ))
)
"""

_CREATE_RUNS_CREATED_AT_INDEX = """
CREATE INDEX IF NOT EXISTS ix_cutover_readiness_runs_created_at
    ON cutover_readiness_runs (created_at)
"""

_CREATE_RUNS_STATUS_INDEX = """
CREATE INDEX IF NOT EXISTS ix_cutover_readiness_runs_status
    ON cutover_readiness_runs (status)
"""

_CREATE_RUNS_SUPERSEDES_INDEX = """
CREATE INDEX IF NOT EXISTS ix_cutover_readiness_runs_supersedes_run_id
    ON cutover_readiness_runs (supersedes_run_id)
"""

_CREATE_RUNS_RECONCILIATION_RUN_INDEX = """
CREATE INDEX IF NOT EXISTS ix_cutover_readiness_runs_reconciliation_run_id
    ON cutover_readiness_runs (reconciliation_run_id)
"""

_GOVERNED_TABLES = ("cutover_readiness_runs",)

# Captured empirically against a real, freshly migrated PostgreSQL 16
# database (the table created directly via `Base.metadata.create_all()`,
# then its own catalog rows read back) -- mirrors 0015-0020's
# `_EXPECTED_COLUMNS` shape exactly: (data_type, udt_name,
# character_maximum_length, is_nullable, column_default).
_EXPECTED_COLUMNS = {
    "cutover_readiness_runs": {
        "id": ("uuid", "uuid", None, "NO", None),
        "status": ("character varying", "varchar", 20, "NO", "'pending'::character varying"),
        "version": ("integer", "int4", None, "NO", "0"),
        "created_by_user_id": ("uuid", "uuid", None, "NO", None),
        "created_at": ("timestamp with time zone", "timestamptz", None, "NO", "now()"),
        "completed_at": ("timestamp with time zone", "timestamptz", None, "YES", None),
        "completed_by_user_id": ("uuid", "uuid", None, "YES", None),
        "application_baseline_sha": ("character varying", "varchar", 40, "NO", None),
        "database_migration_head": ("character varying", "varchar", 255, "NO", None),
        "source_of_truth_strategy": (
            "character varying",
            "varchar",
            30,
            "NO",
            "'hard_cutover'::character varying",
        ),
        "cutover_instant": ("timestamp with time zone", "timestamptz", None, "NO", None),
        "freeze_window_reference": ("character varying", "varchar", 255, "YES", None),
        "equipment_master_import_source_id": ("uuid", "uuid", None, "YES", None),
        "legacy_migration_authority_id": ("uuid", "uuid", None, "YES", None),
        "legacy_coverage_id": ("uuid", "uuid", None, "YES", None),
        "reconciliation_run_id": ("uuid", "uuid", None, "YES", None),
        "reconciliation_signoff_id": ("uuid", "uuid", None, "YES", None),
        "current_state_verified_at": ("timestamp with time zone", "timestamptz", None, "YES", None),
        "current_state_verified_by_user_id": ("uuid", "uuid", None, "YES", None),
        "current_state_verification_scope_count": ("integer", "int4", None, "YES", None),
        "current_state_verification_reference": ("character varying", "varchar", 255, "YES", None),
        "pilot_ward_id": ("uuid", "uuid", None, "YES", None),
        "operational_approver_reference": ("character varying", "varchar", 255, "YES", None),
        "supersedes_run_id": ("uuid", "uuid", None, "YES", None),
    },
}

# Mirrors 0015-0020's `_EXPECTED_CONSTRAINTS` shape -- `pg_get_constraintdef()`
# renders every constraint kind uniformly, including PostgreSQL's own
# auto-generated PK/FK names.
_EXPECTED_CONSTRAINTS = {
    "cutover_readiness_runs": {
        "cutover_readiness_runs_pkey": "PRIMARY KEY (id)",
        "cutover_readiness_runs_created_by_user_id_fkey": (
            "FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT"
        ),
        "cutover_readiness_runs_completed_by_user_id_fkey": (
            "FOREIGN KEY (completed_by_user_id) REFERENCES users(id) ON DELETE RESTRICT"
        ),
        "cutover_readiness_runs_equipment_master_import_source_id_fkey": (
            "FOREIGN KEY (equipment_master_import_source_id) REFERENCES import_sources(id) ON DELETE RESTRICT"
        ),
        "cutover_readiness_runs_legacy_migration_authority_id_fkey": (
            "FOREIGN KEY (legacy_migration_authority_id) REFERENCES legacy_migration_authorities(id) "
            "ON DELETE RESTRICT"
        ),
        "cutover_readiness_runs_legacy_coverage_id_fkey": (
            "FOREIGN KEY (legacy_coverage_id) REFERENCES legacy_migration_authority_coverages(id) "
            "ON DELETE RESTRICT"
        ),
        "cutover_readiness_runs_reconciliation_run_id_fkey": (
            "FOREIGN KEY (reconciliation_run_id) REFERENCES legacy_reconciliation_runs(id) ON DELETE RESTRICT"
        ),
        "cutover_readiness_runs_reconciliation_signoff_id_fkey": (
            "FOREIGN KEY (reconciliation_signoff_id) REFERENCES legacy_reconciliation_signoffs(id) "
            "ON DELETE RESTRICT"
        ),
        "cutover_readiness_runs_current_state_verified_by_user_id_fkey": (
            "FOREIGN KEY (current_state_verified_by_user_id) REFERENCES users(id) ON DELETE RESTRICT"
        ),
        "cutover_readiness_runs_pilot_ward_id_fkey": (
            "FOREIGN KEY (pilot_ward_id) REFERENCES wards(id) ON DELETE RESTRICT"
        ),
        "cutover_readiness_runs_supersedes_run_id_fkey": (
            "FOREIGN KEY (supersedes_run_id) REFERENCES cutover_readiness_runs(id) ON DELETE RESTRICT"
        ),
        "ck_cutover_readiness_runs_status": (
            "CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying, "
            "'completed'::character varying, 'failed'::character varying])::text[])))"
        ),
        "ck_cutover_readiness_runs_version": "CHECK ((version >= 0))",
        "ck_cutover_readiness_runs_source_of_truth_strategy": (
            "CHECK (((source_of_truth_strategy)::text = 'hard_cutover'::text))"
        ),
        "ck_cutover_readiness_runs_baseline_sha_length": (
            "CHECK ((length((application_baseline_sha)::text) = 40))"
        ),
        "ck_cutover_readiness_runs_completed_pair": (
            "CHECK (((completed_at IS NULL) = (completed_by_user_id IS NULL)))"
        ),
        "ck_cutover_readiness_runs_verification_pair": (
            "CHECK (((current_state_verified_at IS NULL) = (current_state_verified_by_user_id IS NULL)))"
        ),
        "ck_cutover_readiness_runs_verification_scope_nonneg": (
            "CHECK (((current_state_verification_scope_count IS NULL) OR "
            "(current_state_verification_scope_count >= 0)))"
        ),
        "ck_cutover_readiness_runs_no_self_supersession": (
            "CHECK (((supersedes_run_id IS NULL) OR (supersedes_run_id <> id)))"
        ),
        "ck_cutover_readiness_runs_completion_requires_evidence": (
            "CHECK ((((status)::text <> 'completed'::text) OR ((equipment_master_import_source_id IS NOT NULL) "
            "AND (legacy_migration_authority_id IS NOT NULL) AND (legacy_coverage_id IS NOT NULL) AND "
            "(reconciliation_run_id IS NOT NULL) AND (reconciliation_signoff_id IS NOT NULL) AND "
            "(current_state_verified_at IS NOT NULL) AND (current_state_verified_by_user_id IS NOT NULL) AND "
            "(completed_at IS NOT NULL) AND (completed_by_user_id IS NOT NULL))))"
        ),
    },
}

# Mirrors 0015-0020's `_EXPECTED_INDEXES` shape.
_EXPECTED_INDEXES = {
    "cutover_readiness_runs": {
        "cutover_readiness_runs_pkey": (
            "CREATE UNIQUE INDEX cutover_readiness_runs_pkey ON public.cutover_readiness_runs USING btree (id)"
        ),
        "ix_cutover_readiness_runs_created_at": (
            "CREATE INDEX ix_cutover_readiness_runs_created_at ON public.cutover_readiness_runs "
            "USING btree (created_at)"
        ),
        "ix_cutover_readiness_runs_status": (
            "CREATE INDEX ix_cutover_readiness_runs_status ON public.cutover_readiness_runs USING btree (status)"
        ),
        "ix_cutover_readiness_runs_supersedes_run_id": (
            "CREATE INDEX ix_cutover_readiness_runs_supersedes_run_id ON public.cutover_readiness_runs "
            "USING btree (supersedes_run_id)"
        ),
        "ix_cutover_readiness_runs_reconciliation_run_id": (
            "CREATE INDEX ix_cutover_readiness_runs_reconciliation_run_id ON public.cutover_readiness_runs "
            "USING btree (reconciliation_run_id)"
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
    """Mirrors `0020_reconciliation_foundation._verify_schema_convergence()`'s
    exact discipline and rationale, applied to this one new PR23B table.
    Required invariant: `expected_governed_objects ==
    actual_governed_objects` -- exact closed-world equality. Any
    non-COMPATIBLE classification aborts the migration with every
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
                f"{table}: unexpected column(s) not part of the PR23B design contract "
                f"(docs/design/PR23_CUTOVER_READINESS_PLAN.md §15/§26): {sorted(unexpected_columns)}. An extra "
                "application column is never silently accepted merely because every expected column also exists."
            )
        unexpected_constraints = _unexpected_object_names(
            bind, _ACTUAL_CONSTRAINT_NAMES_SQL, table, _EXPECTED_CONSTRAINTS[table]
        )
        if unexpected_constraints:
            problems.append(
                f"{table}: unexpected constraint(s) not part of the PR23B design contract: "
                f"{sorted(unexpected_constraints)}."
            )
        unexpected_indexes = _unexpected_object_names(bind, _ACTUAL_INDEX_NAMES_SQL, table, _EXPECTED_INDEXES[table])
        if unexpected_indexes:
            problems.append(
                f"{table}: unexpected index(es) not part of the PR23B design contract: {sorted(unexpected_indexes)}."
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
            "Migration 0021 aborted: the existing PostgreSQL catalog diverges from the PR23B design "
            f"contract (docs/design/PR23_CUTOVER_READINESS_PLAN.md §9/§10/§11/§12/§15/§16/§26) in "
            f"{len(problems)} way(s). Refusing to silently continue with an incompatible historical "
            "schema:\n\n" + "\n\n".join(problems)
        )


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    op.execute(sa.text(_CREATE_RUNS))
    op.execute(sa.text(_CREATE_RUNS_CREATED_AT_INDEX))
    op.execute(sa.text(_CREATE_RUNS_STATUS_INDEX))
    op.execute(sa.text(_CREATE_RUNS_SUPERSEDES_INDEX))
    op.execute(sa.text(_CREATE_RUNS_RECONCILIATION_RUN_INDEX))
    _verify_schema_convergence(bind)


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    op.execute(sa.text("DROP TABLE IF EXISTS cutover_readiness_runs"))
