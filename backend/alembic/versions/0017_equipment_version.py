"""Roadmap PR20B -- Equipment.version optimistic-concurrency column

Revision ID: 0017_equipment_version
Revises: 0016_import_source_blobs
Create Date: 2026-08-12

Roadmap PR20B (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md §24,
architecture-approved). Introduces one new, purely additive column,
`equipment.version` -- an `INTEGER NOT NULL DEFAULT 1` optimistic-
concurrency counter, mirroring `ImportSession.version`'s existing pattern
(app/models/import_session.py, migration 0015). No existing column is
modified. No Equipment Master parser, field mapping, or write path ships
with this slice (§24 PR20C+ scope) -- this is a general Equipment-domain
improvement, independent of PR20's own field-mapping/policy questions
(all three of which remain OPEN Owner Decisions), required as a
prerequisite for a later Equipment Master execute path's optimistic-
concurrency CAS predicate.

**Backfill**: PostgreSQL 11+ supports adding a `NOT NULL` column with a
non-null `DEFAULT` as a single, fast, metadata-only operation -- every
pre-existing row observably reads back `version = 1` without a separate
`UPDATE` statement or full-table rewrite. There is no prior optimistic-
lock history to reconcile, since no version concept has ever existed for
`Equipment` before this migration.

**Fresh-install vs. historical-upgrade convergence**, following the exact
discipline `0015_import_foundation`/`0016_import_source_blobs` established.
`app.models.equipment.Equipment` (already registered in `app/db/base.py`)
now also defines `version`, so `0001_initial.py`'s
`Base.metadata.create_all()` already creates this column on any brand-new
install. This migration's own raw SQL is what adds it on a database that
historically applied `0001`-`0016` before this slice existed.
`_verify_schema_convergence()` below applies the same production-owned,
fail-closed catalog classification pattern as `0016`'s, scoped narrowly to
this one new column only (not the whole `equipment` table's pre-existing
columns, which are outside this migration's ownership and evolve across
many earlier, unrelated migrations) -- the expected value captured
empirically against a real, freshly migrated PostgreSQL 16 database (this
repository's own local instance, migrated through `0016` first, then this
column added and its catalog row read back directly), never hand-guessed.

Only ever runs raw SQL against PostgreSQL (see 0002/0004/0011-0016's
identical dialect-gated pattern) -- SQLite tests create this column via
`Base.metadata.create_all()` directly (`tests/conftest.py`), never via this
migration chain, so ORM model correctness alone is authoritative there.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_equipment_version"
down_revision: Union[str, None] = "0016_import_source_blobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "equipment"
_COLUMN = "version"

_ADD_COLUMN = "ALTER TABLE equipment ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1"
_DROP_COLUMN = "ALTER TABLE equipment DROP COLUMN IF EXISTS version"

# Captured empirically against a real, freshly migrated PostgreSQL 16
# database (this column added directly, then its own catalog row read
# back) -- mirrors 0015/0016's `_EXPECTED_COLUMNS` shape exactly:
# (data_type, udt_name, character_maximum_length, is_nullable, column_default).
_EXPECTED_COLUMN = ("integer", "int4", None, "NO", "1")

_MISSING = "missing"
_COMPATIBLE = "compatible"
_INCOMPATIBLE_DEFINITION = "incompatible_definition"

_COLUMN_SQL = sa.text(
    "SELECT data_type, udt_name, character_maximum_length, is_nullable, column_default "
    "FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
)


def _classify_column(bind, table: str, column: str, expected: tuple) -> tuple[str, tuple | None]:
    row = bind.execute(_COLUMN_SQL, {"t": table, "c": column}).one_or_none()
    if row is None:
        return _MISSING, None
    actual = (row.data_type, row.udt_name, row.character_maximum_length, row.is_nullable, row.column_default)
    return (_COMPATIBLE if actual == expected else _INCOMPATIBLE_DEFINITION), actual


def _verify_schema_convergence(bind) -> None:
    """Mirrors `0016_import_source_blobs._verify_schema_convergence()`'s
    exact discipline, scoped to the single `equipment.version` column this
    migration owns. Required invariant: the column exists with exactly the
    expected physical definition. Any non-COMPATIBLE classification aborts
    the migration with the mismatch described concretely; nothing is ever
    silently dropped, renamed, rebuilt, or coerced. Runs inside Alembic's
    single per-invocation transaction, so raising here rolls back the
    `ADD COLUMN` statement, leaving the pre-migration schema completely
    unchanged. Deliberately does not enumerate `equipment`'s other columns
    as "unexpected" -- unlike 0016's brand-new table, `equipment` predates
    this migration by many earlier, unrelated migrations, and this
    migration owns only the one column it adds.
    """
    kind, actual = _classify_column(bind, _TABLE, _COLUMN, _EXPECTED_COLUMN)
    if kind == _MISSING:
        raise RuntimeError(
            f"Migration 0017 aborted: {_TABLE}.{_COLUMN} does not exist even after this migration's own "
            "ADD COLUMN ran -- this indicates an internal migration bug, not a pre-existing incompatible "
            "schema."
        )
    if kind == _INCOMPATIBLE_DEFINITION:
        raise RuntimeError(
            f"Migration 0017 aborted: {_TABLE}.{_COLUMN} exists but diverges from the PR20B design contract "
            "(docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md §24).\n"
            f"    Expected (data_type, udt_name, char_max_length, is_nullable, column_default) = "
            f"{_EXPECTED_COLUMN!r}\n"
            f"    Actual                                                                        = {actual!r}"
        )


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    op.execute(sa.text(_ADD_COLUMN))
    _verify_schema_convergence(bind)


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    op.execute(sa.text(_DROP_COLUMN))
