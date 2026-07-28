"""make ON DELETE RESTRICT explicit on all 25 foreign keys (Roadmap PR15B, Migration B)

Revision ID: 0013_fk_ondelete_policy
Revises: 0012_timezone_conversion
Create Date: 2026-07-28

Roadmap PR15B (Schema Hygiene), Migration B of three
(docs/design/PR15B_SCHEMA_HYGIENE_PLAN.md §4/§8.2/§8.7, GitHub PR #52,
architecture-approved) -- see §4 for the full FK-by-FK table this docstring
summarizes.

**What this changes, and why it is zero observable behavior change today.**
All 25 foreign keys in this schema currently use PostgreSQL's implicit
`NO ACTION` (`pg_constraint.confdeltype = 'a'`). `NO ACTION` and `RESTRICT`
are functionally identical for every FK here because none is `DEFERRABLE`
(the only real difference between the two only matters for deferrable
constraints) -- and the running application has exactly one `DELETE`
endpoint (`DELETE /equipment/{id}`), which performs a **soft** delete
(`equipment_crud.soft_delete`, setting `deleted_at`), never a real SQL
`DELETE`. So no FK's `ondelete` behavior is exercised by any code path
today; this migration makes the policy explicit, not different.

**Paired with the companion ORM model change (§4 cross-check), not a
database-only change.** `0001_initial.py` bootstraps its entire schema via
`Base.metadata.create_all()`, and `tests/conftest.py` builds the SQLite test
schema the same way, bypassing Alembic entirely. All 24 `ForeignKey()`
declarations across `app/models/*.py` now specify `ondelete="RESTRICT"` in
the same commit as this migration -- the 25th FK
(`user_role_migrations_user_id_fkey`) has no ORM counterpart at all
(`user_role_migrations` is a provenance table created directly via
`op.create_table()` in migration `0009_role_consolidation.py`, never mapped
onto `Base.metadata`), so it is fixed exclusively by this migration acting
against the PostgreSQL catalog, exactly as the other 24 are -- this
migration's logic treats all 25 identically regardless of ORM presence.

**Verify-and-no-op with full semantic-definition comparison (§8.7a/§8.7b),
not `confdeltype` alone.** For each of the 25 named FK constraints, this
migration inspects `pg_constraint` for: referenced table (`confrelid`),
referenced column(s) (`confkey`), local column(s) (`conkey`), `ON UPDATE`
(`confupdtype`), deferrable/deferred state (`condeferrable`/`condeferred`),
and validation state (`convalidated`) -- comparing the complete definition,
not a single field, against this migration's own §4-sourced expectation.
Every FK in this schema is single-column today (confirmed, §4), so column
resolution here does not need to handle composite keys. Outcomes:

  1. **Needs transformation** -- every field matches this migration's
     expectation except `confdeltype = 'a'` (`NO ACTION`): drop and recreate
     the constraint (same name) with `ON DELETE RESTRICT`.
  2. **Already at target state** -- every field matches, including
     `confdeltype = 'r'` (`RESTRICT`) already: no-op, nothing to do (the
     fresh-install-after-ORM-fix case for the 24 ORM-backed FKs, and simply
     "someone already ran this migration" for the 25th).
  3. **Fails closed** -- the constraint is not found under its expected name
     at all, or is found but any field (other than `confdeltype`) does not
     match this migration's expectation, or `confdeltype` is something this
     proposal never intends (`c` CASCADE, `d` SET DEFAULT, `n` SET NULL):
     raises `RuntimeError` naming the constraint and the actual vs. expected
     definition. Never silently repaired, overwritten, or guessed (§8.7c).

**Migration impact:** all changes are `ALTER TABLE ... DROP CONSTRAINT ...
ADD CONSTRAINT ... FOREIGN KEY (...) REFERENCES ... (...) ON DELETE
RESTRICT`-shaped -- metadata-only, no data rewrite. Fully reversible:
downgrade drops the explicit `RESTRICT` constraint and recreates the
implicit-`NO ACTION` one, under the same verify-and-no-op discipline.

Only ever runs against PostgreSQL in this project (see 0002/0004/0011/0012's
identical dialect-gated pattern).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_fk_ondelete_policy"
down_revision: Union[str, None] = "0012_timezone_conversion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


class _FKSpec:
    __slots__ = ("name", "table", "column", "ref_table", "ref_column")

    def __init__(self, name: str, table: str, column: str, ref_table: str, ref_column: str = "id"):
        self.name = name
        self.table = table
        self.column = column
        self.ref_table = ref_table
        self.ref_column = ref_column


# All 25 FKs, per §4's table. Order matches the table for auditability.
_FK_SPECS: tuple[_FKSpec, ...] = (
    _FKSpec("equipment_category_id_fkey", "equipment", "category_id", "equipment_categories"),
    _FKSpec("equipment_department_owner_id_fkey", "equipment", "department_owner_id", "departments"),
    _FKSpec("equipment_current_location_id_fkey", "equipment", "current_location_id", "locations"),
    _FKSpec("equipment_status_history_equipment_id_fkey", "equipment_status_history", "equipment_id", "equipment"),
    _FKSpec(
        "equipment_status_history_changed_by_user_id_fkey",
        "equipment_status_history",
        "changed_by_user_id",
        "users",
    ),
    _FKSpec("pm_schedules_equipment_id_fkey", "pm_schedules", "equipment_id", "equipment"),
    _FKSpec("pm_schedules_performed_by_user_id_fkey", "pm_schedules", "performed_by_user_id", "users"),
    _FKSpec("calibration_schedules_equipment_id_fkey", "calibration_schedules", "equipment_id", "equipment"),
    _FKSpec(
        "calibration_schedules_performed_by_user_id_fkey",
        "calibration_schedules",
        "performed_by_user_id",
        "users",
    ),
    _FKSpec("equipment_attachments_equipment_id_fkey", "equipment_attachments", "equipment_id", "equipment"),
    _FKSpec(
        "equipment_attachments_uploaded_by_user_id_fkey", "equipment_attachments", "uploaded_by_user_id", "users"
    ),
    _FKSpec("notifications_user_id_fkey", "notifications", "user_id", "users"),
    _FKSpec("borrow_transactions_equipment_id_fkey", "borrow_transactions", "equipment_id", "equipment"),
    _FKSpec("borrow_transactions_borrower_user_id_fkey", "borrow_transactions", "borrower_user_id", "users"),
    _FKSpec("borrow_transactions_ward_id_fkey", "borrow_transactions", "ward_id", "wards"),
    _FKSpec("borrow_transactions_department_id_fkey", "borrow_transactions", "department_id", "departments"),
    _FKSpec(
        "borrow_transactions_pickup_location_id_fkey", "borrow_transactions", "pickup_location_id", "locations"
    ),
    _FKSpec(
        "borrow_transactions_dropoff_location_id_fkey", "borrow_transactions", "dropoff_location_id", "locations"
    ),
    _FKSpec("borrow_transactions_received_by_user_id_fkey", "borrow_transactions", "received_by_user_id", "users"),
    _FKSpec(
        "transaction_attachments_transaction_id_fkey",
        "transaction_attachments",
        "transaction_id",
        "borrow_transactions",
    ),
    _FKSpec(
        "transaction_attachments_uploaded_by_user_id_fkey", "transaction_attachments", "uploaded_by_user_id", "users"
    ),
    _FKSpec("audit_logs_user_id_fkey", "audit_logs", "user_id", "users"),
    _FKSpec("wards_department_id_fkey", "wards", "department_id", "departments"),
    _FKSpec("users_role_id_fkey", "users", "role_id", "roles"),
    _FKSpec("user_role_migrations_user_id_fkey", "user_role_migrations", "user_id", "users"),
)

_NO_ACTION = "a"
_RESTRICT = "r"
_ALREADY_INTENDED_ONUPDATE = "a"  # NO ACTION -- this proposal never changes ON UPDATE


def _fetch_fk(bind, *, name: str):
    row = bind.execute(
        sa.text(
            """
            SELECT
                c.oid,
                c.conrelid::regclass::text AS local_table,
                c.confrelid::regclass::text AS ref_table,
                (SELECT attname FROM pg_attribute
                 WHERE attrelid = c.conrelid AND attnum = c.conkey[1]) AS local_column,
                (SELECT attname FROM pg_attribute
                 WHERE attrelid = c.confrelid AND attnum = c.confkey[1]) AS ref_column,
                c.confdeltype::text AS confdeltype,
                c.confupdtype::text AS confupdtype,
                c.condeferrable,
                c.condeferred,
                c.convalidated,
                array_length(c.conkey, 1) AS key_length
            FROM pg_constraint c
            WHERE c.conname = :name AND c.contype = 'f'
            """
        ),
        {"name": name},
    ).one_or_none()
    return row


def _expected_matches(row, spec: _FKSpec) -> bool:
    return (
        row.local_table == spec.table
        and row.ref_table == spec.ref_table
        and row.local_column == spec.column
        and row.ref_column == spec.ref_column
        and row.key_length == 1
        and row.confupdtype == _ALREADY_INTENDED_ONUPDATE
        and not row.condeferrable
        and not row.condeferred
        and row.convalidated
    )


def _describe(row) -> str:
    return (
        f"local_table={row.local_table}, local_column={row.local_column}, "
        f"ref_table={row.ref_table}, ref_column={row.ref_column}, "
        f"confdeltype={row.confdeltype!r}, confupdtype={row.confupdtype!r}, "
        f"condeferrable={row.condeferrable}, condeferred={row.condeferred}, "
        f"convalidated={row.convalidated}, key_length={row.key_length}"
    )


def _apply_restrict(bind, spec: _FKSpec) -> None:
    row = _fetch_fk(bind, name=spec.name)

    if row is None:
        raise RuntimeError(
            f"Migration 0013 aborted: expected foreign key constraint '{spec.name}' on table "
            f"'{spec.table}' was not found in the PostgreSQL catalog. This migration expects it "
            "to already exist (created by an earlier migration's implicit or explicit FK "
            "declaration) -- refusing to guess or create it fresh. Inspect the schema manually "
            "before re-running this migration."
        )

    if not _expected_matches(row, spec):
        raise RuntimeError(
            f"Migration 0013 aborted: foreign key constraint '{spec.name}' exists but its "
            f"definition does not match what this migration expects.\n"
            f"  Found:    {_describe(row)}\n"
            f"  Expected: local_table={spec.table}, local_column={spec.column}, "
            f"ref_table={spec.ref_table}, ref_column={spec.ref_column}, confupdtype='a', "
            "condeferrable=False, condeferred=False, convalidated=True.\n"
            "This may indicate a partially-applied prior migration attempt or manual "
            "intervention. Refusing to silently repair or overwrite -- inspect and resolve "
            "manually before re-running this migration."
        )

    if row.confdeltype == _RESTRICT:
        # Already at target state -- intentional no-op (§8.7a outcome 2).
        return

    if row.confdeltype != _NO_ACTION:
        raise RuntimeError(
            f"Migration 0013 aborted: foreign key constraint '{spec.name}' has an unexpected "
            f"ON DELETE action confdeltype={row.confdeltype!r} (expected 'a' NO ACTION or "
            "already 'r' RESTRICT). This proposal never introduces CASCADE/SET DEFAULT/SET "
            "NULL for this relationship -- refusing to silently proceed. Inspect and resolve "
            "manually before re-running this migration."
        )

    op.execute(f"ALTER TABLE {spec.table} DROP CONSTRAINT {spec.name}")
    op.execute(
        f"ALTER TABLE {spec.table} ADD CONSTRAINT {spec.name} "
        f"FOREIGN KEY ({spec.column}) REFERENCES {spec.ref_table} ({spec.ref_column}) "
        "ON DELETE RESTRICT"
    )


def _revert_to_no_action(bind, spec: _FKSpec) -> None:
    row = _fetch_fk(bind, name=spec.name)

    if row is None:
        raise RuntimeError(
            f"Migration 0013 downgrade aborted: expected foreign key constraint '{spec.name}' "
            f"on table '{spec.table}' was not found. Inspect the schema manually before "
            "re-running this downgrade."
        )

    if row.confdeltype == _NO_ACTION:
        # Already downgraded -- no-op.
        return

    if row.confdeltype != _RESTRICT:
        raise RuntimeError(
            f"Migration 0013 downgrade aborted: foreign key constraint '{spec.name}' has an "
            f"unexpected ON DELETE action confdeltype={row.confdeltype!r} (expected 'r' "
            "RESTRICT or already 'a' NO ACTION). Inspect and resolve manually before "
            "re-running this downgrade."
        )

    op.execute(f"ALTER TABLE {spec.table} DROP CONSTRAINT {spec.name}")
    op.execute(
        f"ALTER TABLE {spec.table} ADD CONSTRAINT {spec.name} "
        f"FOREIGN KEY ({spec.column}) REFERENCES {spec.ref_table} ({spec.ref_column})"
    )


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    for spec in _FK_SPECS:
        _apply_restrict(bind, spec)


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    for spec in reversed(_FK_SPECS):
        _revert_to_no_action(bind, spec)
