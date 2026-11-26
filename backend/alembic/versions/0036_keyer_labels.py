"""Display-only BME keyer labels on borrow transactions (Owner Governance D22)

Revision ID: 0036_keyer_labels
Revises: 0035_standby_summary
Create Date: 2026-11-26

Purely additive, nullable, no default, no foreign key:

- `borrow_transactions.dispatch_keyer_label` VARCHAR(100) NULL
- `borrow_transactions.receipt_keyer_label` VARCHAR(100) NULL

Free-text display label of the pool staff member (the legacy sheet's "ชื่อ BME")
for rows replayed by the legacy sheet sync. Never a user, never an actor
(audit and `borrower_user_id` / `received_by_user_id` are unchanged). Printed
forms and Excel show it in the BME column when present, else the user's name.

Only runs raw SQL against PostgreSQL (dialect-gated like 0002-0035); SQLite
tests build the schema from ORM metadata.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0036_keyer_labels"
down_revision: Union[str, None] = "0035_standby_summary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UPGRADE = [
    "ALTER TABLE borrow_transactions ADD COLUMN IF NOT EXISTS dispatch_keyer_label VARCHAR(100)",
    "ALTER TABLE borrow_transactions ADD COLUMN IF NOT EXISTS receipt_keyer_label VARCHAR(100)",
]
_DOWNGRADE = [
    "ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS receipt_keyer_label",
    "ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS dispatch_keyer_label",
]
_EXPECTED = {
    "dispatch_keyer_label": ("character varying", 100, "YES"),
    "receipt_keyer_label": ("character varying", 100, "YES"),
}


def _verify_schema_convergence() -> None:
    rows = op.get_bind().execute(
        sa.text(
            "SELECT column_name, data_type, character_maximum_length, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'borrow_transactions' "
            "AND column_name IN ('dispatch_keyer_label', 'receipt_keyer_label')"
        )
    ).fetchall()
    actual = {r[0]: tuple(r[1:]) for r in rows}
    if actual != _EXPECTED:
        raise RuntimeError(f"borrow_transactions keyer label columns are {actual!r}, expected {_EXPECTED!r}.")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for statement in _UPGRADE:
        op.execute(sa.text(statement))
    _verify_schema_convergence()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for statement in _DOWNGRADE:
        op.execute(sa.text(statement))
