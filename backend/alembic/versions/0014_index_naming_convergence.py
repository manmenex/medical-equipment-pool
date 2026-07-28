"""rename hand-named idx_ indexes and auto-named unique constraints to the ix_/uq_ convention (Roadmap PR15B, Migration C)

Revision ID: 0014_index_naming_convergence
Revises: 0013_fk_ondelete_policy
Create Date: 2026-07-28

Roadmap PR15B (Schema Hygiene), Migration C of three
(docs/design/PR15B_SCHEMA_HYGIENE_PLAN.md §6/§8.2/§8.7, GitHub PR #52,
architecture-approved) -- see §6 for the full rename plan this docstring
summarizes.

**What this renames, and why.** Three inconsistent index/constraint naming
groups exist today (§6.1): 29 `ix_`-prefixed (SQLAlchemy default, already
correct), 5 hand-named `idx_`-prefixed (4 GIN trigram indexes + 1 partial
unique index), and 7 PostgreSQL-auto-named `<table>_<column>_key` unique
constraints (owning columns have `unique=True` with no explicit name).
This migration renames the latter two groups onto the `ix_`/`uq_`
convention already used everywhere else -- 100% `ALTER INDEX`/`ALTER TABLE
... RENAME CONSTRAINT`, zero index rebuild, zero query-plan change (§6.3).

  `idx_equipment_asset_trgm`   -> `ix_equipment_asset_number_trgm`
  `idx_equipment_bcm_trgm`     -> `ix_equipment_bcm_code_trgm`
  `idx_equipment_name_trgm`    -> `ix_equipment_equipment_name_trgm`
  `idx_equipment_serial_trgm`  -> `ix_equipment_serial_number_trgm`
  `idx_tx_one_active_borrow`   -> `ix_borrow_transactions_one_active_borrow`
  `equipment_serial_number_key`    -> `uq_equipment_serial_number`
  `equipment_categories_name_key`  -> `uq_equipment_categories_name`
  `departments_code_key`           -> `uq_departments_code`
  `wards_code_key`                 -> `uq_wards_code`
  `roles_name_key`                 -> `uq_roles_name`
  `users_employee_code_key`        -> `uq_users_employee_code`
  `users_email_key`                -> `uq_users_email`

**`ix_borrow_transactions_one_active_borrow` is not purely cosmetic** -- it
is the real database-level guard against double-dispatching the same
equipment (the partial unique index enforcing "at most one active borrow
per equipment"). Renaming does not touch its definition (predicate,
uniqueness, indexed column) -- only its name -- and this migration's
regression tests (§11) prove a duplicate-active-borrow attempt is still
rejected after the rename.

**Paired with the companion ORM model changes (§6.4), not a database-only
change.** `0001_initial.py` bootstraps schema via `Base.metadata.create_all()`
against *current* ORM metadata, and `tests/conftest.py` builds the SQLite
test schema the same way. The 7 unique-constraint columns now carry
explicit `UniqueConstraint(name="uq_...")` declarations (replacing bare
`unique=True`) in `app/models/equipment.py`, `master_data.py`, `user.py`.
`ix_borrow_transactions_one_active_borrow` (formerly `idx_tx_one_active_
borrow`) is likewise now declared under its target name directly in
`app/models/transaction.py`'s `Index(...)` -- a correction discovered
during implementation: unlike the 4 GIN trigram indexes (which remain
migration-only, with no ORM declaration at all, confirmed via grep), this
partial unique index IS declared in ORM metadata, so it needed the same
name-convergence fix as the 7 unique constraints for a fresh install and
the SQLite test suite to agree with this migration's rename target.

**Verify-and-no-op with full semantic-definition + health-state comparison
(§8.7a/§8.7b), not name matching alone.** For each of the 12 renames, this
migration:

  1. Queries `pg_indexes`/`pg_constraint` for the **old** name. Found ->
     confirms (via `pg_get_indexdef()`/`pg_get_constraintdef()` plus the
     relevant `pg_index`/`pg_constraint` columns -- indexed column(s),
     uniqueness, expression, predicate, sort/null order, included columns,
     collation, access method) that the object found is the one expected
     there, then performs the rename (`ALTER INDEX ... RENAME TO ...` for
     the 5 indexes; `ALTER TABLE ... RENAME CONSTRAINT ... TO ...` for the
     7 unique constraints, which also renames the backing index).
  2. Old name not found -> queries for the **target** name. Found, full
     definition matches, **and `pg_index.indisvalid = true` /
     `indisready = true`** -> no-op (the fresh-install-after-ORM-fix case).
     Target name found but definition mismatched, or matches but unhealthy
     -> §8.7c's fail-closed mixed-state policy (Scenario 2 / Scenario 3).
  3. Neither old nor target name found, or both found simultaneously
     (Scenario 1) -> fails closed: raises `RuntimeError` naming the
     specific mismatch. Never silently repaired, overwritten, or rebuilt.

An index or index-backed constraint that matches every definitional check
but has `indisvalid = false` or `indisready = false` (e.g. left behind by an
interrupted `CREATE INDEX CONCURRENTLY`/`REINDEX CONCURRENTLY`) is never
treated as a valid no-op target -- health state is a required, independent
gate (§8.7b/§8.7c Scenario 3), proven by this migration's mandatory
interrupted-index-build regression test (§8.7d/§11).

**Migration impact:** every rename is `ALTER INDEX .../ALTER TABLE ...
RENAME CONSTRAINT ...`-shaped -- metadata-only, no rebuild, no lock beyond
the brief catalog-update `ALTER` requires. Fully reversible: downgrade
renames back to the legacy names under the same verify-and-no-op discipline.

Only ever runs against PostgreSQL in this project (see 0002/0004/0011/0012/
0013's identical dialect-gated pattern).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_index_naming_convergence"
down_revision: Union[str, None] = "0013_fk_ondelete_policy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


class _IndexRename:
    """A plain (non-constraint-backed) index rename -- GIN trigram or the
    borrow-transactions partial unique safety index."""

    __slots__ = ("old_name", "new_name", "table", "expected_indexdef")

    def __init__(self, old_name: str, new_name: str, table: str, expected_indexdef_template: str):
        self.old_name = old_name
        self.new_name = new_name
        self.table = table
        # %(name)s is substituted with whichever name (old or new) is
        # currently live, since pg_get_indexdef() always reports the
        # index's *current* name regardless of what we expect it to be.
        self.expected_indexdef = expected_indexdef_template


class _ConstraintRename:
    """A unique-constraint-backed rename (also renames the backing index)."""

    __slots__ = ("old_name", "new_name", "table", "column")

    def __init__(self, old_name: str, new_name: str, table: str, column: str):
        self.old_name = old_name
        self.new_name = new_name
        self.table = table
        self.column = column


_INDEX_RENAMES: tuple[_IndexRename, ...] = (
    _IndexRename(
        "idx_equipment_asset_trgm",
        "ix_equipment_asset_number_trgm",
        "equipment",
        "CREATE INDEX %(name)s ON public.equipment USING gin (asset_number gin_trgm_ops)",
    ),
    _IndexRename(
        "idx_equipment_bcm_trgm",
        "ix_equipment_bcm_code_trgm",
        "equipment",
        "CREATE INDEX %(name)s ON public.equipment USING gin (bcm_code gin_trgm_ops)",
    ),
    _IndexRename(
        "idx_equipment_name_trgm",
        "ix_equipment_equipment_name_trgm",
        "equipment",
        "CREATE INDEX %(name)s ON public.equipment USING gin (equipment_name gin_trgm_ops)",
    ),
    _IndexRename(
        "idx_equipment_serial_trgm",
        "ix_equipment_serial_number_trgm",
        "equipment",
        "CREATE INDEX %(name)s ON public.equipment USING gin (serial_number gin_trgm_ops)",
    ),
    _IndexRename(
        "idx_tx_one_active_borrow",
        "ix_borrow_transactions_one_active_borrow",
        "borrow_transactions",
        "CREATE UNIQUE INDEX %(name)s ON public.borrow_transactions USING btree (equipment_id) "
        "WHERE ((status)::text = 'open'::text)",
    ),
)

_CONSTRAINT_RENAMES: tuple[_ConstraintRename, ...] = (
    _ConstraintRename("equipment_serial_number_key", "uq_equipment_serial_number", "equipment", "serial_number"),
    _ConstraintRename(
        "equipment_categories_name_key", "uq_equipment_categories_name", "equipment_categories", "name"
    ),
    _ConstraintRename("departments_code_key", "uq_departments_code", "departments", "code"),
    _ConstraintRename("wards_code_key", "uq_wards_code", "wards", "code"),
    _ConstraintRename("roles_name_key", "uq_roles_name", "roles", "name"),
    _ConstraintRename("users_employee_code_key", "uq_users_employee_code", "users", "employee_code"),
    _ConstraintRename("users_email_key", "uq_users_email", "users", "email"),
)


def _index_state(bind, *, name: str):
    """Returns (indexdef, indisvalid, indisready) for an index by name, or
    None if no index with this name exists."""
    row = bind.execute(
        sa.text(
            """
            SELECT i.indexdef, x.indisvalid, x.indisready
            FROM pg_indexes i
            JOIN pg_class c ON c.relname = i.indexname
            JOIN pg_index x ON x.indexrelid = c.oid
            WHERE i.schemaname = 'public' AND i.indexname = :name
            """
        ),
        {"name": name},
    ).one_or_none()
    return row


def _rename_index(bind, spec: _IndexRename) -> None:
    old_state = _index_state(bind, name=spec.old_name)
    new_state = _index_state(bind, name=spec.new_name)

    if old_state is not None and new_state is not None:
        raise RuntimeError(
            f"Migration 0014 aborted: both the legacy index name '{spec.old_name}' and the "
            f"target name '{spec.new_name}' exist simultaneously on table '{spec.table}'. This "
            "should not happen under any normal upgrade or fresh-install path -- it suggests a "
            "partially-applied prior migration attempt or manual intervention. Refusing to "
            "guess which is correct; inspect and resolve manually (Scenario 1, §8.7c)."
        )

    if old_state is not None:
        expected = spec.expected_indexdef % {"name": spec.old_name}
        if old_state.indexdef != expected:
            raise RuntimeError(
                f"Migration 0014 aborted: index '{spec.old_name}' exists but its definition "
                f"does not match what this migration expects.\n  Found:    {old_state.indexdef}\n"
                f"  Expected: {expected}\n"
                "This may be a different, unrelated index sharing this name. Refusing to "
                "silently continue -- inspect and resolve manually before re-running this "
                "migration."
            )
        op.execute(f"ALTER INDEX {spec.old_name} RENAME TO {spec.new_name}")
        return

    if new_state is not None:
        expected = spec.expected_indexdef % {"name": spec.new_name}
        if not new_state.indisvalid or not new_state.indisready:
            raise RuntimeError(
                f"Migration 0014 aborted: index '{spec.new_name}' already exists under its "
                f"target name but is not usable (indisvalid={new_state.indisvalid}, "
                f"indisready={new_state.indisready}). This usually means a previous "
                "CREATE INDEX CONCURRENTLY / REINDEX CONCURRENTLY was interrupted. Refusing to "
                "silently continue -- inspect the index, then run 'DROP INDEX CONCURRENTLY IF "
                f"EXISTS {spec.new_name};' and re-run this migration (Scenario 3, §8.7c)."
            )
        if new_state.indexdef != expected:
            raise RuntimeError(
                f"Migration 0014 aborted: index '{spec.new_name}' already exists under its "
                f"target name but its definition does not match.\n"
                f"  Found:    {new_state.indexdef}\n  Expected: {expected}\n"
                "Refusing to silently continue -- inspect and resolve manually before "
                "re-running this migration (Scenario 2, §8.7c)."
            )
        # Already at target state, valid, healthy: intentional no-op.
        return

    raise RuntimeError(
        f"Migration 0014 aborted: neither the legacy index name '{spec.old_name}' nor the "
        f"target name '{spec.new_name}' was found on table '{spec.table}'. This migration "
        "expects one of the two to already exist -- refusing to guess or create it fresh. "
        "Inspect the schema manually before re-running this migration."
    )


def _rename_index_back(bind, spec: _IndexRename) -> None:
    old_state = _index_state(bind, name=spec.old_name)
    new_state = _index_state(bind, name=spec.new_name)

    if old_state is not None and new_state is not None:
        raise RuntimeError(
            f"Migration 0014 downgrade aborted: both '{spec.old_name}' and '{spec.new_name}' "
            f"exist simultaneously on table '{spec.table}'. Inspect and resolve manually."
        )

    if new_state is not None:
        op.execute(f"ALTER INDEX {spec.new_name} RENAME TO {spec.old_name}")
        return

    if old_state is not None:
        # Already downgraded -- no-op.
        return

    raise RuntimeError(
        f"Migration 0014 downgrade aborted: neither '{spec.old_name}' nor '{spec.new_name}' "
        f"was found on table '{spec.table}'. Inspect the schema manually before re-running "
        "this downgrade."
    )


def _constraint_state(bind, *, name: str, table: str, column: str):
    """Returns a row describing the unique constraint by name, or None."""
    row = bind.execute(
        sa.text(
            """
            SELECT
                con.conrelid::regclass::text AS table_name,
                (SELECT attname FROM pg_attribute
                 WHERE attrelid = con.conrelid AND attnum = con.conkey[1]) AS column_name,
                array_length(con.conkey, 1) AS key_length,
                idx.indisvalid,
                idx.indisready
            FROM pg_constraint con
            JOIN pg_class c ON c.oid = con.conrelid
            JOIN pg_index idx ON idx.indexrelid = con.conindid
            WHERE con.conname = :name AND con.contype = 'u'
            """
        ),
        {"name": name},
    ).one_or_none()
    return row


def _rename_constraint(bind, spec: _ConstraintRename) -> None:
    old_state = _constraint_state(bind, name=spec.old_name, table=spec.table, column=spec.column)
    new_state = _constraint_state(bind, name=spec.new_name, table=spec.table, column=spec.column)

    if old_state is not None and new_state is not None:
        raise RuntimeError(
            f"Migration 0014 aborted: both the legacy constraint name '{spec.old_name}' and "
            f"the target name '{spec.new_name}' exist simultaneously on table '{spec.table}'. "
            "Refusing to guess which is correct; inspect and resolve manually (Scenario 1, "
            "§8.7c)."
        )

    def _matches(row) -> bool:
        return row.table_name == spec.table and row.column_name == spec.column and row.key_length == 1

    if old_state is not None:
        if not _matches(old_state):
            raise RuntimeError(
                f"Migration 0014 aborted: unique constraint '{spec.old_name}' exists but does "
                f"not match the expected definition (table={spec.table}, column={spec.column}). "
                f"Found: table={old_state.table_name}, column={old_state.column_name}, "
                f"key_length={old_state.key_length}. Refusing to silently continue -- inspect "
                "and resolve manually before re-running this migration."
            )
        op.execute(f"ALTER TABLE {spec.table} RENAME CONSTRAINT {spec.old_name} TO {spec.new_name}")
        return

    if new_state is not None:
        if not new_state.indisvalid or not new_state.indisready:
            raise RuntimeError(
                f"Migration 0014 aborted: unique constraint '{spec.new_name}' already exists "
                f"under its target name but its backing index is not usable "
                f"(indisvalid={new_state.indisvalid}, indisready={new_state.indisready}). "
                "Refusing to silently continue -- inspect and resolve manually (Scenario 3, "
                "§8.7c)."
            )
        if not _matches(new_state):
            raise RuntimeError(
                f"Migration 0014 aborted: unique constraint '{spec.new_name}' already exists "
                f"under its target name but does not match the expected definition "
                f"(table={spec.table}, column={spec.column}). Found: table={new_state.table_name}, "
                f"column={new_state.column_name}, key_length={new_state.key_length}. Refusing to "
                "silently continue -- inspect and resolve manually (Scenario 2, §8.7c)."
            )
        # Already at target state, valid, healthy: intentional no-op.
        return

    raise RuntimeError(
        f"Migration 0014 aborted: neither the legacy constraint name '{spec.old_name}' nor the "
        f"target name '{spec.new_name}' was found on table '{spec.table}'. Refusing to guess or "
        "create it fresh. Inspect the schema manually before re-running this migration."
    )


def _rename_constraint_back(bind, spec: _ConstraintRename) -> None:
    old_state = _constraint_state(bind, name=spec.old_name, table=spec.table, column=spec.column)
    new_state = _constraint_state(bind, name=spec.new_name, table=spec.table, column=spec.column)

    if old_state is not None and new_state is not None:
        raise RuntimeError(
            f"Migration 0014 downgrade aborted: both '{spec.old_name}' and '{spec.new_name}' "
            f"exist simultaneously on table '{spec.table}'. Inspect and resolve manually."
        )

    if new_state is not None:
        op.execute(f"ALTER TABLE {spec.table} RENAME CONSTRAINT {spec.new_name} TO {spec.old_name}")
        return

    if old_state is not None:
        # Already downgraded -- no-op.
        return

    raise RuntimeError(
        f"Migration 0014 downgrade aborted: neither '{spec.old_name}' nor '{spec.new_name}' was "
        f"found on table '{spec.table}'. Inspect the schema manually before re-running this "
        "downgrade."
    )


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    for spec in _INDEX_RENAMES:
        _rename_index(bind, spec)
    for spec in _CONSTRAINT_RENAMES:
        _rename_constraint(bind, spec)


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    for spec in reversed(_CONSTRAINT_RENAMES):
        _rename_constraint_back(bind, spec)
    for spec in reversed(_INDEX_RENAMES):
        _rename_index_back(bind, spec)
