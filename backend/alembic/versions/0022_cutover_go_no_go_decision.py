"""Roadmap PR23D -- Go/No-Go Decision + Current-State Re-Issue Support

Revision ID: 0022_cutover_go_no_go_decision
Revises: 0021_cutover_readiness
Create Date: 2026-08-26

Roadmap PR23D (docs/design/PR23_CUTOVER_READINESS_PLAN.md §12 Gate G,
§13 Go/No-Go, §14 Authorization, §15 Evidence/Audit, §16 Concurrency/
Freshness, §26 OD-PR23-3/OD-PR23-6). Introduces one new, purely
additive table: `cutover_go_no_go_decisions` -- the immutable final
Go/No-Go decision for one `CutoverReadinessRun`, exactly the additive
decision/sign-off table `app.models.cutover_readiness`'s own PR23B
module docstring anticipated. No existing table is modified. This
slice implements no current-state re-issue write endpoint (the existing
`POST /borrow` issue workflow is reused unchanged) and no frontend
(PR23E).

**Fresh-install vs. historical-upgrade convergence**, following the
exact discipline migrations `0015`-`0021` established (see those
migrations' own extensive docstrings for the full rationale -- not
restated here). `app.models.cutover_readiness` (registered in
`app/db/base.py`) already defines the ORM model, so `0001_initial.py`'s
`Base.metadata.create_all()` already creates this table on any
brand-new install. This migration's own raw SQL is what creates it on
a database that historically applied `0001`-`0021` before this slice
existed. `_verify_schema_convergence()` below is the same
production-owned, fail-closed catalog classification pattern as
`0015`-`0021`'s -- every expected value captured empirically against a
real, freshly migrated PostgreSQL 16 database (this repository's own
local instance, migrated through `0021` first, then this table created
directly via `Base.metadata.create_all()` and its own catalog rows
read back), never hand-guessed. No auto-generated foreign-key
constraint name on this table is truncated by PostgreSQL's own
NAMEDATALEN(63) limit -- every FK name below is exactly as PostgreSQL
generated it.

Only ever runs raw SQL against PostgreSQL (see 0002/0004/0011-0021's
identical dialect-gated pattern) -- SQLite tests create this table via
`Base.metadata.create_all()` directly (`tests/conftest.py`), never via
this migration chain, so ORM model correctness alone is authoritative
there.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022_cutover_go_no_go_decision"
down_revision: Union[str, None] = "0021_cutover_readiness"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CREATE_DECISIONS = """
CREATE TABLE IF NOT EXISTS cutover_go_no_go_decisions (
    id UUID NOT NULL PRIMARY KEY,
    cutover_readiness_run_id UUID NOT NULL REFERENCES cutover_readiness_runs(id) ON DELETE RESTRICT,
    decision VARCHAR(10) NOT NULL,
    recorded_by_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    run_version_at_decision INTEGER NOT NULL,
    acknowledged_warning_codes JSONB NOT NULL,
    no_go_reason VARCHAR(2000),
    CONSTRAINT uq_cutover_go_no_go_decisions_cutover_readiness_run_id UNIQUE (cutover_readiness_run_id),
    CONSTRAINT ck_cutover_go_no_go_decisions_decision
        CHECK (decision IN ('GO','NO_GO')),
    CONSTRAINT ck_cutover_go_no_go_decisions_run_version_at_decision
        CHECK (run_version_at_decision >= 0),
    CONSTRAINT ck_cutover_go_no_go_decisions_no_go_reason_length
        CHECK (LENGTH(no_go_reason) <= 2000)
)
"""

_CREATE_DECISIONS_RECORDED_AT_INDEX = """
CREATE INDEX IF NOT EXISTS ix_cutover_go_no_go_decisions_recorded_at
    ON cutover_go_no_go_decisions (recorded_at)
"""

_GOVERNED_TABLES = ("cutover_go_no_go_decisions",)

# Captured empirically against a real, freshly migrated PostgreSQL 16
# database (the table created directly via `Base.metadata.create_all()`,
# then its own catalog rows read back) -- mirrors 0015-0021's
# `_EXPECTED_COLUMNS` shape exactly: (data_type, udt_name,
# character_maximum_length, is_nullable, column_default).
_EXPECTED_COLUMNS = {
    "cutover_go_no_go_decisions": {
        "id": ("uuid", "uuid", None, "NO", None),
        "cutover_readiness_run_id": ("uuid", "uuid", None, "NO", None),
        "decision": ("character varying", "varchar", 10, "NO", None),
        "recorded_by_user_id": ("uuid", "uuid", None, "NO", None),
        "recorded_at": ("timestamp with time zone", "timestamptz", None, "NO", "now()"),
        "run_version_at_decision": ("integer", "int4", None, "NO", None),
        "acknowledged_warning_codes": ("jsonb", "jsonb", None, "NO", None),
        "no_go_reason": ("character varying", "varchar", 2000, "YES", None),
    },
}

# Mirrors 0015-0021's `_EXPECTED_CONSTRAINTS` shape -- `pg_get_constraintdef()`
# renders every constraint kind uniformly, including PostgreSQL's own
# auto-generated PK/FK names.
_EXPECTED_CONSTRAINTS = {
    "cutover_go_no_go_decisions": {
        "cutover_go_no_go_decisions_pkey": "PRIMARY KEY (id)",
        "cutover_go_no_go_decisions_cutover_readiness_run_id_fkey": (
            "FOREIGN KEY (cutover_readiness_run_id) REFERENCES cutover_readiness_runs(id) ON DELETE RESTRICT"
        ),
        "cutover_go_no_go_decisions_recorded_by_user_id_fkey": (
            "FOREIGN KEY (recorded_by_user_id) REFERENCES users(id) ON DELETE RESTRICT"
        ),
        "uq_cutover_go_no_go_decisions_cutover_readiness_run_id": "UNIQUE (cutover_readiness_run_id)",
        "ck_cutover_go_no_go_decisions_decision": (
            "CHECK (((decision)::text = ANY ((ARRAY['GO'::character varying, 'NO_GO'::character varying])"
            "::text[])))"
        ),
        "ck_cutover_go_no_go_decisions_run_version_at_decision": "CHECK ((run_version_at_decision >= 0))",
        "ck_cutover_go_no_go_decisions_no_go_reason_length": (
            "CHECK ((length((no_go_reason)::text) <= 2000))"
        ),
    },
}

# Mirrors 0015-0021's `_EXPECTED_INDEXES` shape.
_EXPECTED_INDEXES = {
    "cutover_go_no_go_decisions": {
        "cutover_go_no_go_decisions_pkey": (
            "CREATE UNIQUE INDEX cutover_go_no_go_decisions_pkey ON public.cutover_go_no_go_decisions "
            "USING btree (id)"
        ),
        "uq_cutover_go_no_go_decisions_cutover_readiness_run_id": (
            "CREATE UNIQUE INDEX uq_cutover_go_no_go_decisions_cutover_readiness_run_id ON "
            "public.cutover_go_no_go_decisions USING btree (cutover_readiness_run_id)"
        ),
        "ix_cutover_go_no_go_decisions_recorded_at": (
            "CREATE INDEX ix_cutover_go_no_go_decisions_recorded_at ON public.cutover_go_no_go_decisions "
            "USING btree (recorded_at)"
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
    """Mirrors `0021_cutover_readiness._verify_schema_convergence()`'s
    exact discipline and rationale, applied to this one new PR23D table.
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
                f"{table}: unexpected column(s) not part of the PR23D design contract "
                f"(docs/design/PR23_CUTOVER_READINESS_PLAN.md §12/§13/§15/§26): {sorted(unexpected_columns)}. "
                "An extra application column is never silently accepted merely because every expected column "
                "also exists."
            )
        unexpected_constraints = _unexpected_object_names(
            bind, _ACTUAL_CONSTRAINT_NAMES_SQL, table, _EXPECTED_CONSTRAINTS[table]
        )
        if unexpected_constraints:
            problems.append(
                f"{table}: unexpected constraint(s) not part of the PR23D design contract: "
                f"{sorted(unexpected_constraints)}."
            )
        unexpected_indexes = _unexpected_object_names(bind, _ACTUAL_INDEX_NAMES_SQL, table, _EXPECTED_INDEXES[table])
        if unexpected_indexes:
            problems.append(
                f"{table}: unexpected index(es) not part of the PR23D design contract: {sorted(unexpected_indexes)}."
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
            "Migration 0022 aborted: the existing PostgreSQL catalog diverges from the PR23D design "
            f"contract (docs/design/PR23_CUTOVER_READINESS_PLAN.md §12/§13/§15/§16/§26) in "
            f"{len(problems)} way(s). Refusing to silently continue with an incompatible historical "
            "schema:\n\n" + "\n\n".join(problems)
        )


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    op.execute(sa.text(_CREATE_DECISIONS))
    op.execute(sa.text(_CREATE_DECISIONS_RECORDED_AT_INDEX))
    _verify_schema_convergence(bind)


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    op.execute(sa.text("DROP TABLE IF EXISTS cutover_go_no_go_decisions"))
