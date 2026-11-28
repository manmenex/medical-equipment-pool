"""HN retention marker `hn_recorded` (D31)

Revision ID: 0042_hn_recorded
Revises: 0041_system_heartbeats
Create Date: 2026-11-28

`borrow_transactions.hn_recorded` = an HN was EVER recorded on this
transaction; it survives the 2-year erasure of `hn_ciphertext`. It replaces
the old `has_hn` column (same meaning while HN was never erased): backfilled
as `has_hn OR hn_ciphertext IS NOT NULL`, then `has_hn` is dropped (the ORM
keeps `has_hn` as an alias of `hn_recorded`). Dialect-gated like 0002-0041.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0042_hn_recorded"
down_revision: Union[str, None] = "0041_system_heartbeats"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UPGRADE_SQL = (
    "ALTER TABLE borrow_transactions ADD COLUMN IF NOT EXISTS hn_recorded BOOLEAN NOT NULL DEFAULT false",
    "UPDATE borrow_transactions SET hn_recorded = true WHERE has_hn OR hn_ciphertext IS NOT NULL",
    "ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS has_hn",
)
DOWNGRADE_SQL = (
    "ALTER TABLE borrow_transactions ADD COLUMN IF NOT EXISTS has_hn BOOLEAN NOT NULL DEFAULT false",
    "UPDATE borrow_transactions SET has_hn = hn_recorded",
    "ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS hn_recorded",
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for stmt in UPGRADE_SQL:
        op.execute(sa.text(stmt))


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for stmt in DOWNGRADE_SQL:
        op.execute(sa.text(stmt))
