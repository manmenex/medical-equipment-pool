"""Transaction corrections: voided status and restore/void columns (Owner Governance 2026-11-27, D28)

Revision ID: 0039_transaction_corrections
Revises: 0038_export_hn_scope
Create Date: 2026-11-27

Additive and nullable (legacy rows keep NULLs), plus one constraint change:

- `borrow_transactions.prior_equipment_status` VARCHAR(30) NULL
- `borrow_transactions.closed_by_redispatch_transaction_id` UUID NULL -> borrow_transactions(id)
- `borrow_transactions.receipt_saved_at` TIMESTAMPTZ NULL (server time of the receipt save; undo window base)
- `borrow_transactions.voided_at` TIMESTAMPTZ NULL
- `borrow_transactions.voided_by_user_id` UUID NULL -> users(id)
- `borrow_transactions.void_reason` VARCHAR(500) NULL
- `borrow_transactions.corrected_by_transaction_id` UUID NULL -> borrow_transactions(id)
- `ck_borrow_transactions_status_open_closed` now allows 'voided' as well
  (the constraint keeps its historical name so the fresh and historical
  paths converge).

A legacy dispatch without `prior_equipment_status` restores to
AVAILABLE_AT_POOL when voided. The partial unique index
`idx_tx_one_active_borrow` (status = 'open') is unchanged: a voided row is
never open.

Downgrade refuses (fails closed) while any row is `voided`, since the old
constraint cannot represent it.

Only runs raw SQL against PostgreSQL (dialect-gated like 0002-0038); SQLite
tests build the schema from ORM metadata.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0039_transaction_corrections"
down_revision: Union[str, None] = "0038_export_hn_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONSTRAINT = "ck_borrow_transactions_status_open_closed"
_UPGRADE = [
    "ALTER TABLE borrow_transactions ADD COLUMN IF NOT EXISTS prior_equipment_status VARCHAR(30)",
    "ALTER TABLE borrow_transactions ADD COLUMN IF NOT EXISTS closed_by_redispatch_transaction_id UUID "
    "REFERENCES borrow_transactions(id) ON DELETE RESTRICT",
    "ALTER TABLE borrow_transactions ADD COLUMN IF NOT EXISTS receipt_saved_at TIMESTAMP WITH TIME ZONE",
    "ALTER TABLE borrow_transactions ADD COLUMN IF NOT EXISTS voided_at TIMESTAMP WITH TIME ZONE",
    "ALTER TABLE borrow_transactions ADD COLUMN IF NOT EXISTS voided_by_user_id UUID "
    "REFERENCES users(id) ON DELETE RESTRICT",
    "ALTER TABLE borrow_transactions ADD COLUMN IF NOT EXISTS void_reason VARCHAR(500)",
    "ALTER TABLE borrow_transactions ADD COLUMN IF NOT EXISTS corrected_by_transaction_id UUID "
    "REFERENCES borrow_transactions(id) ON DELETE RESTRICT",
    f"ALTER TABLE borrow_transactions DROP CONSTRAINT IF EXISTS {_CONSTRAINT}",
    f"ALTER TABLE borrow_transactions ADD CONSTRAINT {_CONSTRAINT} CHECK (status IN ('open', 'closed', 'voided'))",
]
_DOWNGRADE = [
    f"ALTER TABLE borrow_transactions DROP CONSTRAINT IF EXISTS {_CONSTRAINT}",
    f"ALTER TABLE borrow_transactions ADD CONSTRAINT {_CONSTRAINT} CHECK (status IN ('open', 'closed'))",
    "ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS corrected_by_transaction_id",
    "ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS void_reason",
    "ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS voided_by_user_id",
    "ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS voided_at",
    "ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS receipt_saved_at",
    "ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS closed_by_redispatch_transaction_id",
    "ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS prior_equipment_status",
]
_NEW_COLUMNS = {
    "prior_equipment_status": ("character varying", 30),
    "closed_by_redispatch_transaction_id": ("uuid", None),
    "receipt_saved_at": ("timestamp with time zone", None),
    "voided_at": ("timestamp with time zone", None),
    "voided_by_user_id": ("uuid", None),
    "void_reason": ("character varying", 500),
    "corrected_by_transaction_id": ("uuid", None),
}


def _verify() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT column_name, data_type, character_maximum_length, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'borrow_transactions' AND column_name = ANY(:c)"
        ),
        {"c": list(_NEW_COLUMNS)},
    ).fetchall()
    actual = {r[0]: (r[1], r[2], r[3]) for r in rows}
    expected = {name: (dt, ln, "YES") for name, (dt, ln) in _NEW_COLUMNS.items()}
    if actual != expected:
        raise RuntimeError(f"borrow_transactions D28 columns are {actual!r}, expected {expected!r}.")
    definition = bind.execute(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"), {"n": _CONSTRAINT}
    ).scalar()
    if definition is None or "voided" not in definition:
        raise RuntimeError(f"{_CONSTRAINT} is {definition!r}, expected it to allow 'voided'.")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for statement in _UPGRADE:
        op.execute(sa.text(statement))
    _verify()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    voided = bind.execute(sa.text("SELECT count(*) FROM borrow_transactions WHERE status = 'voided'")).scalar()
    if voided:
        raise RuntimeError(
            f"Cannot downgrade 0039: {voided} voided transaction(s) exist and the previous schema cannot hold them."
        )
    for statement in _DOWNGRADE:
        op.execute(sa.text(statement))
