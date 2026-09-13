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

**Not paired with an ORM rename for this one object.** Unlike the 7 unique
constraints (which now carry explicit `UniqueConstraint(name="uq_...")`
declarations in `app/models/equipment.py`, `master_data.py`, `user.py`,
replacing bare `unique=True`), `idx_tx_one_active_borrow` is deliberately
**not** renamed in `app/models/transaction.py`'s `Index(...)` declaration.
`migration 0007_transaction_lifecycle.py` (an immutable historical
migration) unconditionally issues `DROP INDEX IF EXISTS
idx_tx_one_active_borrow` / `CREATE UNIQUE INDEX idx_tx_one_active_borrow
...` on every run, regardless of what a fresh install's `0001_initial.py`
bootstrap already produced from ORM metadata. If the ORM declared the
target name instead, a fresh install would end up with *two* indexes --
the ORM-created one under the target name, and a second one 0007
unconditionally (re)creates under the legacy name -- a genuine duplicate-
index bug, not a convergence fix (discovered and reverted during
implementation). Renaming this index to its target name is therefore
`0014`'s job on *every* path (fresh or historical) -- it is never already
at target state on the fresh-install path the way the 7 unique constraints
are, and this migration's verify-and-no-op logic reflects that: the
legacy-name branch is the one normally taken for this object, not a
transient historical-only case. The 4 GIN trigram indexes remain
migration-only with no ORM declaration at all (confirmed via grep) --
unaffected by this distinction.

**Verify-and-no-op with full semantic-definition + health-state comparison
(§8.7a/§8.7b), not name matching alone.** For each of the 12 renames, this
migration inspects `pg_get_indexdef()`/`pg_get_constraintdef()` plus the
underlying `pg_index`/`pg_constraint`/`pg_am`/`pg_attribute` columns --
access method, uniqueness, indexed column(s), expressions, predicates,
per-column collation (checked against the indexed column's own collation,
catching an unexpected `COLLATE` override), included columns, and (for the
7 unique constraints) deferrable/initially-deferred state and `NULLS NOT
DISTINCT` -- **plus** `pg_index.indisvalid`/`indisready` health flags.

**One shared classification helper, `_classify_rename()`, drives every
execution path identically** (design-compliance requirement: no code path
may rename, recreate, or no-op based on partial verification). It is used,
unmodified, for:

  - the legacy-name side of `upgrade()`,
  - the target-name side of `upgrade()`,
  - the legacy-name side of `downgrade()` (i.e. `downgrade()`'s own
    "already-reverted" no-op case, from the *target* name's perspective),
  - the target-name side of `downgrade()` (i.e. `downgrade()`'s own
    "needs reverting" case, from the *legacy* name's perspective).

`downgrade()` calls the identical classifier with the old/new roles
swapped -- it never renames or recreates based on presence/absence alone;
full semantic verification and health checks run first, on *both* names,
in *both* directions, exactly as `upgrade()` does. Outcomes:

  1. **Needs transformation** -- found under one name, semantically
     verified as a full match, **and healthy** -- perform the rename
     (`ALTER INDEX ... RENAME TO ...` for the 5 indexes; `ALTER TABLE ...
     RENAME CONSTRAINT ... TO ...` for the 7 unique constraints, which also
     renames the backing index).
  2. **Already at target state** -- found under the other name, full
     definition matches, **and healthy** -- no-op (the fresh-install-
     after-ORM-fix case for the 7 renamed unique constraints).
  3. **Fails closed** -- found under either name but the *semantic
     definition* does not match (Scenario 2, §8.7c), found under either
     name but **unhealthy** (`indisvalid = false` or `indisready = false`,
     Scenario 3, §8.7c) -- checked identically whichever name it is found
     under, not just the target name -- both names found simultaneously
     (Scenario 1, §8.7c), or neither name found at all: raises
     `RuntimeError` naming the specific mismatch. Never silently repaired,
     overwritten, or rebuilt.

An index or index-backed constraint that matches every definitional check
but has `indisvalid = false` or `indisready = false` (e.g. left behind by an
interrupted `CREATE INDEX CONCURRENTLY`/`REINDEX CONCURRENTLY`) is never
treated as a valid state to rename from *or* to -- health state is a
required, independent gate checked on both sides of both directions
(§8.7b/§8.7c Scenario 3), proven by this migration's mandatory
interrupted-index-build regression tests (§8.7d/§11), including the case
where the *legacy*-named object itself is unhealthy.

**PR15B-H3: a name backed by only one of {index, unique constraint} is a
third, distinct catalog state -- PARTIAL -- never collapsed into ABSENT.**
For the 7 constraint renames, a name is only genuinely absent if *neither*
a `pg_indexes` row *nor* a `pg_constraint` row exists under it. `_classify_
rename()` checks for PARTIAL on both the legacy and target name, in both
directions, before it ever reaches the ABSENT/COMPLETE-based outcomes below
-- a standalone index with no owning constraint (or vice versa) found under
either name always raises `RuntimeError` before any rename, no-op, drop, or
recreate is attempted.

**Migration impact:** every rename is `ALTER INDEX .../ALTER TABLE ...
RENAME CONSTRAINT ...`-shaped -- metadata-only, no rebuild, no lock beyond
the brief catalog-update `ALTER` requires. Fully reversible: downgrade
renames back to the legacy names under the identical semantic-verification
helper as upgrade.

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

_NEEDS_TRANSFORM = "needs_transform"
_NOOP = "noop"

# The complete structural+health query shared by both plain indexes and
# constraint-backed indexes (a named unique constraint's backing index is
# always named identically to the constraint itself, confirmed against a
# live PostgreSQL 16 instance) -- one query, reused for every object kind
# this migration touches.
_INDEX_ROW_SQL = sa.text(
    """
    SELECT
        ix.indexdef,
        i.indisvalid,
        i.indisready,
        i.indisunique,
        am.amname AS access_method,
        (i.indnkeyatts = i.indnatts) AS no_included_columns,
        NOT EXISTS (
            SELECT 1
            FROM generate_series(0, i.indnkeyatts - 1) AS k(pos)
            JOIN pg_attribute a
              ON a.attrelid = i.indrelid AND a.attnum = i.indkey[k.pos]
            WHERE i.indcollation[k.pos] IS DISTINCT FROM a.attcollation
        ) AS collation_matches_columns,
        i.indnullsnotdistinct
    FROM pg_indexes ix
    JOIN pg_class c ON c.relname = ix.indexname AND c.relnamespace = 'public'::regnamespace
    JOIN pg_index i ON i.indexrelid = c.oid
    JOIN pg_am am ON am.oid = c.relam
    WHERE ix.schemaname = 'public' AND ix.indexname = :name
    """
)

_UNIQUE_CONSTRAINT_ROW_SQL = sa.text(
    """
    SELECT pg_get_constraintdef(oid) AS condef, condeferrable, condeferred
    FROM pg_constraint
    WHERE conname = :name AND contype = 'u'
    """
)


def _index_row(bind, name: str):
    """Full structural+health state for an index by name (whether or not
    it backs a unique constraint), or None if no index with this name
    exists. This is the single source of index-catalog truth this
    migration uses -- both `_IndexVerifier` and `_ConstraintVerifier`
    below call it."""
    return bind.execute(_INDEX_ROW_SQL, {"name": name}).one_or_none()


def _unique_constraint_row(bind, name: str):
    """`pg_constraint`-specific fields for a named unique constraint, or
    None if no such constraint exists."""
    return bind.execute(_UNIQUE_CONSTRAINT_ROW_SQL, {"name": name}).one_or_none()


class _CatalogState:
    """PR15B-H3: tags a verifier's `fetch()` result as exactly one of three
    distinct states -- never just "found" (a raw row) or "not found" (None)
    -- so a genuinely PARTIAL catalog state (only one of an index/unique-
    constraint pair exists under a name) is never silently collapsed into
    ABSENT (neither exists). `.data` carries the fetched row (or row tuple)
    only when `.kind == COMPLETE`; `.detail` carries a human-readable
    description of what was actually found, only when `.kind == PARTIAL`."""

    ABSENT = "absent"
    COMPLETE = "complete"
    PARTIAL = "partial"

    __slots__ = ("kind", "data", "detail")

    def __init__(self, kind: str, *, data=None, detail: Union[str, None] = None):
        self.kind = kind
        self.data = data
        self.detail = detail

    @property
    def is_absent(self) -> bool:
        return self.kind == self.ABSENT

    @property
    def is_complete(self) -> bool:
        return self.kind == self.COMPLETE

    @property
    def is_partial(self) -> bool:
        return self.kind == self.PARTIAL


class _IndexVerifier:
    """Semantic verifier for a plain (non-constraint-backed) index rename
    -- the 4 GIN trigram indexes and the borrow-transactions partial
    unique safety index."""

    def __init__(self, *, unique: bool, access_method: str):
        self.unique = unique
        self.access_method = access_method

    def fetch(self, bind, name: str) -> _CatalogState:
        row = _index_row(bind, name)
        if row is None:
            return _CatalogState(_CatalogState.ABSENT)
        return _CatalogState(_CatalogState.COMPLETE, data=row)

    def matches(self, state, expected_indexdef: str) -> bool:
        return (
            state.indexdef == expected_indexdef
            and state.indisunique == self.unique
            and state.access_method == self.access_method
            and state.no_included_columns
            and state.collation_matches_columns
        )

    @staticmethod
    def healthy(state) -> bool:
        return bool(state.indisvalid) and bool(state.indisready)


class _ConstraintVerifier:
    """Semantic verifier for a unique-constraint-backed rename (also
    renames the backing index). Reuses `_index_row()` for the structural/
    health half of the check -- a named unique constraint's backing index
    is always named identically to the constraint (confirmed live), so no
    separate index-name resolution step is needed."""

    unique = True
    access_method = "btree"  # the only access method PostgreSQL supports for UNIQUE

    def fetch(self, bind, name: str) -> _CatalogState:
        index_row = _index_row(bind, name)
        constraint_row = _unique_constraint_row(bind, name)

        if index_row is None and constraint_row is None:
            return _CatalogState(_CatalogState.ABSENT)

        if index_row is not None and constraint_row is not None:
            return _CatalogState(_CatalogState.COMPLETE, data=(index_row, constraint_row))

        # PR15B-H3: exactly one of {index, unique constraint} exists under
        # this name -- a genuinely PARTIAL catalog state, distinct from and
        # never reported as ABSENT.
        return _CatalogState(
            _CatalogState.PARTIAL,
            detail=(
                f"a standalone index named '{name}' "
                + ("exists" if index_row is not None else "does NOT exist")
                + f", and a unique constraint named '{name}' "
                + ("exists" if constraint_row is not None else "does NOT exist")
                + " -- a named unique constraint and its backing index must both exist or both "
                "be absent under the same name"
            ),
        )

    def matches(self, state, expected_condef: str) -> bool:
        index_state, constraint_state = state
        return (
            constraint_state.condef == expected_condef
            and not constraint_state.condeferrable
            and not constraint_state.condeferred
            and not index_state.indnullsnotdistinct
            and index_state.indisunique == self.unique
            and index_state.access_method == self.access_method
            and index_state.no_included_columns
            and index_state.collation_matches_columns
        )

    @staticmethod
    def healthy(state) -> bool:
        index_state, _constraint_state = state
        return bool(index_state.indisvalid) and bool(index_state.indisready)


def _classify_rename(
    bind,
    verifier,
    *,
    old_name: str,
    new_name: str,
    old_expected,
    new_expected,
    table: str,
    direction: str,
) -> str:
    """The single shared classification helper (design-compliance
    requirement) driving every execution path in this migration: the
    legacy-name check, the target-name check, `upgrade()`, and
    `downgrade()` (called with `old_name`/`new_name` and their matching
    `*_expected` values swapped). Full semantic verification and health
    checks run identically on *both* names before any outcome is decided --
    no path may classify from presence/absence alone.
    """
    old_state = verifier.fetch(bind, old_name)
    new_state = verifier.fetch(bind, new_name)

    # PR15B-H3: PARTIAL is checked first, before anything else -- it must
    # never fall through to (and be silently treated as) ABSENT, and must
    # never be reached only after an outcome has already been decided.
    if old_state.is_partial:
        raise RuntimeError(
            f"Migration 0014 {direction} aborted: '{old_name}' is in a partial catalog state on "
            f"table '{table}' -- {old_state.detail}. Refusing to rename, no-op, or otherwise "
            f"treat '{old_name}' as absent. Inspect and resolve manually before re-running this "
            f"{direction} (PR15B-H3)."
        )
    if new_state.is_partial:
        raise RuntimeError(
            f"Migration 0014 {direction} aborted: '{new_name}' is in a partial catalog state on "
            f"table '{table}' -- {new_state.detail}. Refusing to rename, no-op, or otherwise "
            f"treat '{new_name}' as absent. Inspect and resolve manually before re-running this "
            f"{direction} (PR15B-H3)."
        )

    if old_state.is_complete and new_state.is_complete:
        raise RuntimeError(
            f"Migration 0014 {direction} aborted: both '{old_name}' and '{new_name}' exist "
            f"simultaneously on table '{table}'. This should not happen under any normal "
            "upgrade/downgrade or fresh-install path -- it suggests a partially-applied prior "
            "migration attempt or manual intervention. Refusing to guess which is correct; "
            f"inspect and resolve manually before re-running this {direction} (Scenario 1, "
            "§8.7c)."
        )

    if old_state.is_complete:
        if not verifier.matches(old_state.data, old_expected):
            raise RuntimeError(
                f"Migration 0014 {direction} aborted: '{old_name}' exists but its definition "
                f"does not match what this migration expects. Refusing to silently continue -- "
                f"inspect and resolve manually before re-running this {direction} (Scenario 2, "
                "§8.7c)."
            )
        if not verifier.healthy(old_state.data):
            raise RuntimeError(
                f"Migration 0014 {direction} aborted: '{old_name}' exists with a matching "
                "definition but is not usable (indisvalid/indisready). This usually means a "
                "previous CREATE INDEX CONCURRENTLY / REINDEX CONCURRENTLY was interrupted. "
                "Refusing to silently continue -- inspect the index and resolve manually before "
                f"re-running this {direction} (Scenario 3, §8.7c)."
            )
        return _NEEDS_TRANSFORM

    if new_state.is_complete:
        if not verifier.healthy(new_state.data):
            raise RuntimeError(
                f"Migration 0014 {direction} aborted: '{new_name}' already exists under its "
                "target name but is not usable (indisvalid/indisready). This usually means a "
                "previous CREATE INDEX CONCURRENTLY / REINDEX CONCURRENTLY was interrupted. "
                f"Refusing to silently continue -- inspect the index, then run 'DROP INDEX "
                f"CONCURRENTLY IF EXISTS {new_name};' and re-run this {direction} (Scenario 3, "
                "§8.7c)."
            )
        if not verifier.matches(new_state.data, new_expected):
            raise RuntimeError(
                f"Migration 0014 {direction} aborted: '{new_name}' already exists under its "
                "target name but its definition does not match. Refusing to silently continue "
                f"-- inspect and resolve manually before re-running this {direction} (Scenario "
                "2, §8.7c)."
            )
        # Already at target state, semantically verified, healthy:
        # intentional no-op -- reached only after both checks above passed.
        return _NOOP

    # Both ABSENT (never PARTIAL -- that was ruled out above).
    raise RuntimeError(
        f"Migration 0014 {direction} aborted: neither '{old_name}' nor '{new_name}' was found "
        f"on table '{table}'. This migration expects one of the two to already exist -- "
        f"refusing to guess or create it fresh. Inspect the schema manually before re-running "
        f"this {direction}."
    )


class _IndexRename:
    """A plain (non-constraint-backed) index rename -- GIN trigram or the
    borrow-transactions partial unique safety index."""

    __slots__ = ("old_name", "new_name", "table", "indexdef_template", "verifier")

    def __init__(self, old_name: str, new_name: str, table: str, expected_indexdef_template: str, *, unique: bool, access_method: str):
        self.old_name = old_name
        self.new_name = new_name
        self.table = table
        # %(name)s is substituted with whichever name (old or new) is
        # currently live, since pg_get_indexdef() always reports the
        # index's *current* name regardless of what we expect it to be.
        self.indexdef_template = expected_indexdef_template
        self.verifier = _IndexVerifier(unique=unique, access_method=access_method)

    def expected_indexdef(self, name: str) -> str:
        return self.indexdef_template % {"name": name}


class _ConstraintRename:
    """A unique-constraint-backed rename (also renames the backing index)."""

    __slots__ = ("old_name", "new_name", "table", "column", "expected_condef", "verifier")

    def __init__(self, old_name: str, new_name: str, table: str, column: str):
        self.old_name = old_name
        self.new_name = new_name
        self.table = table
        self.column = column
        # pg_get_constraintdef() for a plain UNIQUE constraint never
        # mentions the constraint's own name, so the expected definition
        # is identical regardless of which name (old or new) it is
        # currently found under.
        self.expected_condef = f"UNIQUE ({column})"
        self.verifier = _ConstraintVerifier()


_INDEX_RENAMES: tuple[_IndexRename, ...] = (
    _IndexRename(
        "idx_equipment_asset_trgm",
        "ix_equipment_asset_number_trgm",
        "equipment",
        "CREATE INDEX %(name)s ON public.equipment USING gin (asset_number gin_trgm_ops)",
        unique=False,
        access_method="gin",
    ),
    _IndexRename(
        "idx_equipment_bcm_trgm",
        "ix_equipment_bcm_code_trgm",
        "equipment",
        "CREATE INDEX %(name)s ON public.equipment USING gin (bcm_code gin_trgm_ops)",
        unique=False,
        access_method="gin",
    ),
    _IndexRename(
        "idx_equipment_name_trgm",
        "ix_equipment_equipment_name_trgm",
        "equipment",
        "CREATE INDEX %(name)s ON public.equipment USING gin (equipment_name gin_trgm_ops)",
        unique=False,
        access_method="gin",
    ),
    _IndexRename(
        "idx_equipment_serial_trgm",
        "ix_equipment_serial_number_trgm",
        "equipment",
        "CREATE INDEX %(name)s ON public.equipment USING gin (serial_number gin_trgm_ops)",
        unique=False,
        access_method="gin",
    ),
    _IndexRename(
        "idx_tx_one_active_borrow",
        "ix_borrow_transactions_one_active_borrow",
        "borrow_transactions",
        "CREATE UNIQUE INDEX %(name)s ON public.borrow_transactions USING btree (equipment_id) "
        "WHERE ((status)::text = 'open'::text)",
        unique=True,
        access_method="btree",
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


def _rename_index(bind, spec: _IndexRename, *, direction: str = "upgrade") -> None:
    outcome = _classify_rename(
        bind,
        spec.verifier,
        old_name=spec.old_name,
        new_name=spec.new_name,
        old_expected=spec.expected_indexdef(spec.old_name),
        new_expected=spec.expected_indexdef(spec.new_name),
        table=spec.table,
        direction=direction,
    )
    if outcome == _NEEDS_TRANSFORM:
        op.execute(f"ALTER INDEX {spec.old_name} RENAME TO {spec.new_name}")


def _rename_index_back(bind, spec: _IndexRename) -> None:
    # Downgrade: the same shared classifier, with the old/new roles
    # swapped -- "old" (source) is now the current target name, "new"
    # (destination) is the legacy name being restored.
    outcome = _classify_rename(
        bind,
        spec.verifier,
        old_name=spec.new_name,
        new_name=spec.old_name,
        old_expected=spec.expected_indexdef(spec.new_name),
        new_expected=spec.expected_indexdef(spec.old_name),
        table=spec.table,
        direction="downgrade",
    )
    if outcome == _NEEDS_TRANSFORM:
        op.execute(f"ALTER INDEX {spec.new_name} RENAME TO {spec.old_name}")


def _rename_constraint(bind, spec: _ConstraintRename, *, direction: str = "upgrade") -> None:
    outcome = _classify_rename(
        bind,
        spec.verifier,
        old_name=spec.old_name,
        new_name=spec.new_name,
        old_expected=spec.expected_condef,
        new_expected=spec.expected_condef,
        table=spec.table,
        direction=direction,
    )
    if outcome == _NEEDS_TRANSFORM:
        op.execute(f"ALTER TABLE {spec.table} RENAME CONSTRAINT {spec.old_name} TO {spec.new_name}")


def _rename_constraint_back(bind, spec: _ConstraintRename) -> None:
    outcome = _classify_rename(
        bind,
        spec.verifier,
        old_name=spec.new_name,
        new_name=spec.old_name,
        old_expected=spec.expected_condef,
        new_expected=spec.expected_condef,
        table=spec.table,
        direction="downgrade",
    )
    if outcome == _NEEDS_TRANSFORM:
        op.execute(f"ALTER TABLE {spec.table} RENAME CONSTRAINT {spec.new_name} TO {spec.old_name}")


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
