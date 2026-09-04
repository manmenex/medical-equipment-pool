"""Roadmap PR20A -- import_source_blobs durable byte storage

Revision ID: 0016_import_source_blobs
Revises: 0015_import_foundation
Create Date: 2026-08-12

Roadmap PR20A (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md §6.2,
architecture-approved via the merged Design PR #89). Introduces one new,
purely additive table, `import_source_blobs`: 1:1 durable byte storage for
a registered `ImportSource`, colocated in the same PostgreSQL database so
a source's checksum/byte-size metadata and its actual bytes are always
finalized together in one physical transaction (§6.2's atomicity
contract -- no saga/orphan-cleanup machinery is needed for this storage
choice). No existing table is modified. No Equipment Master parser,
field mapping, or write path ships with this slice (§24 PR20A scope) --
source ingestion/verification/retention/adapter-context infrastructure
only.

**Fresh-install vs. historical-upgrade convergence**, following the exact
discipline migration `0015_import_foundation` established for the four
PR19A1 tables (see that migration's own extensive docstring for the full
rationale -- not restated here). `app.models.import_session` (already
registered in `app/db/base.py`) now also defines `ImportSourceBlob`, so
`0001_initial.py`'s `Base.metadata.create_all()` already creates this
table on any brand-new install. This migration's own raw SQL is what
creates it on a database that historically applied `0001`-`0015` before
this slice existed. `_verify_schema_convergence()` below is the same
production-owned, fail-closed catalog classification pattern as `0015`'s
(closed-world column/constraint/index equality, index/constraint health
gates, relation-scoped constraint lookups) applied to this one table --
every expected value captured empirically against a real, freshly
migrated PostgreSQL 16 database (this repository's own local instance,
migrated through `0015` first, then this table created and its catalog
rows read back directly), never hand-guessed.

Only ever runs raw SQL against PostgreSQL (see 0002/0004/0011/0012/0013/
0014/0015's identical dialect-gated pattern) -- SQLite tests create this
table via `Base.metadata.create_all()` directly (`tests/conftest.py`),
never via this migration chain, so ORM model correctness alone is
authoritative there.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016_import_source_blobs"
down_revision: Union[str, None] = "0015_import_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CREATE_IMPORT_SOURCE_BLOBS = """
CREATE TABLE IF NOT EXISTS import_source_blobs (
    import_source_id UUID NOT NULL PRIMARY KEY REFERENCES import_sources(id) ON DELETE RESTRICT,
    content BYTEA NOT NULL
)
"""

_GOVERNED_TABLE = "import_source_blobs"

# Captured empirically against a real, freshly migrated PostgreSQL 16
# database (this table created directly, then its own catalog rows read
# back) -- mirrors 0015's `_EXPECTED_COLUMNS` shape exactly:
# (data_type, udt_name, character_maximum_length, is_nullable, column_default).
_EXPECTED_COLUMNS = {
    "content": ("bytea", "bytea", None, "NO", None),
    "import_source_id": ("uuid", "uuid", None, "NO", None),
}

# Mirrors 0015's `_EXPECTED_CONSTRAINTS` shape -- `pg_get_constraintdef()`
# renders every constraint kind uniformly, including PostgreSQL's own
# auto-generated PK/FK names.
_EXPECTED_CONSTRAINTS = {
    "import_source_blobs_pkey": "PRIMARY KEY (import_source_id)",
    "import_source_blobs_import_source_id_fkey": (
        "FOREIGN KEY (import_source_id) REFERENCES import_sources(id) ON DELETE RESTRICT"
    ),
}

# Mirrors 0015's `_EXPECTED_INDEXES` shape -- the PK-backing index is the
# only index this table has; no additional lookup index is needed since
# every read path (`ImportSourceReader.open_verified`, retention's
# `DELETE ... WHERE import_source_id = ...`) is already a primary-key
# equality lookup.
_EXPECTED_INDEXES = {
    "import_source_blobs_pkey": (
        "CREATE UNIQUE INDEX import_source_blobs_pkey ON public.import_source_blobs USING btree (import_source_id)"
    ),
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
    """Mirrors `0015_import_foundation._verify_schema_convergence()`'s
    exact discipline and rationale, applied to `import_source_blobs`
    alone. Required invariant: `expected_governed_objects ==
    actual_governed_objects` -- exact closed-world equality. Any
    non-COMPATIBLE classification aborts the migration with every mismatch
    described concretely; nothing is ever silently dropped, renamed,
    rebuilt, or coerced. Runs inside Alembic's single per-invocation
    transaction, so raising here rolls back every DDL statement this
    migration issued, leaving the pre-migration schema completely
    unchanged."""
    problems: list[str] = []

    unexpected_columns = _unexpected_object_names(bind, _ACTUAL_COLUMN_NAMES_SQL, _GOVERNED_TABLE, _EXPECTED_COLUMNS)
    if unexpected_columns:
        problems.append(
            f"{_GOVERNED_TABLE}: unexpected column(s) not part of the PR20A design contract "
            f"(docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md §6.2): {sorted(unexpected_columns)}. "
            "An extra application column is never silently accepted merely because every expected "
            "column also exists."
        )
    unexpected_constraints = _unexpected_object_names(
        bind, _ACTUAL_CONSTRAINT_NAMES_SQL, _GOVERNED_TABLE, _EXPECTED_CONSTRAINTS
    )
    if unexpected_constraints:
        problems.append(
            f"{_GOVERNED_TABLE}: unexpected constraint(s) not part of the PR20A design contract: "
            f"{sorted(unexpected_constraints)}."
        )
    unexpected_indexes = _unexpected_object_names(bind, _ACTUAL_INDEX_NAMES_SQL, _GOVERNED_TABLE, _EXPECTED_INDEXES)
    if unexpected_indexes:
        problems.append(
            f"{_GOVERNED_TABLE}: unexpected index(es) not part of the PR20A design contract: "
            f"{sorted(unexpected_indexes)}."
        )

    for column, expected in _EXPECTED_COLUMNS.items():
        kind, actual = _classify_column(bind, _GOVERNED_TABLE, column, expected)
        if kind == _MISSING:
            problems.append(
                f"{_GOVERNED_TABLE}.{column}: column does not exist even after this migration's own "
                "CREATE TABLE ran -- this indicates an internal migration bug, not a pre-existing "
                "incompatible schema."
            )
        elif kind == _INCOMPATIBLE_DEFINITION:
            problems.append(
                f"{_GOVERNED_TABLE}.{column}: column exists but diverges from the design contract.\n"
                f"    Expected (data_type, udt_name, char_max_length, is_nullable, column_default) = {expected!r}\n"
                f"    Actual                                                                        = {actual!r}"
            )

    for name, expected_def in _EXPECTED_CONSTRAINTS.items():
        kind, actual = _classify_constraint(bind, _GOVERNED_TABLE, name, expected_def)
        if kind == _MISSING:
            problems.append(
                f"{_GOVERNED_TABLE}: constraint '{name}' does not exist on this table even after this "
                "migration's own DDL ran -- this indicates an internal migration bug, not a pre-existing "
                "incompatible schema."
            )
        elif kind == _INCOMPATIBLE_DEFINITION:
            actual_def, _validated = actual
            problems.append(
                f"{_GOVERNED_TABLE}: constraint '{name}' exists on this table but its definition diverges.\n"
                f"    Expected: {expected_def}\n"
                f"    Actual:   {actual_def}"
            )
        elif kind == _INCOMPATIBLE_HEALTH:
            actual_def, validated = actual
            problems.append(
                f"{_GOVERNED_TABLE}: constraint '{name}' matches its expected definition but is not "
                f"validated (pg_constraint.convalidated={validated})."
            )

    for name, expected_def in _EXPECTED_INDEXES.items():
        kind, actual = _classify_index(bind, name, expected_def)
        if kind == _MISSING:
            problems.append(
                f"{_GOVERNED_TABLE}: index '{name}' does not exist even after this migration's own CREATE "
                "INDEX ran -- this indicates an internal migration bug, not a pre-existing incompatible "
                "schema."
            )
        elif kind == _INCOMPATIBLE_DEFINITION:
            actual_def, _valid, _ready = actual
            problems.append(
                f"{_GOVERNED_TABLE}: index '{name}' exists but its definition diverges (CREATE INDEX IF "
                "NOT EXISTS silently no-ops against a same-named index regardless of its actual "
                "definition).\n"
                f"    Expected: {expected_def}\n"
                f"    Actual:   {actual_def}"
            )
        elif kind == _INCOMPATIBLE_HEALTH:
            actual_def, valid, ready = actual
            problems.append(
                f"{_GOVERNED_TABLE}: index '{name}' matches its expected definition but is not usable "
                f"(pg_index.indisvalid={valid}, indisready={ready})."
            )

    if problems:
        raise RuntimeError(
            "Migration 0016 aborted: the existing PostgreSQL catalog diverges from the PR20A design "
            f"contract (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md §6.2) in {len(problems)} way(s). "
            "Refusing to silently continue with an incompatible historical schema:\n\n" + "\n\n".join(problems)
        )


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    op.execute(sa.text(_CREATE_IMPORT_SOURCE_BLOBS))
    _verify_schema_convergence(bind)


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    op.execute(sa.text("DROP TABLE IF EXISTS import_source_blobs"))
