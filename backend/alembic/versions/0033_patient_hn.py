"""Optional patient HN on a dispatch, encrypted at rest (Roadmap PR29)

Revision ID: 0033_patient_hn
Revises: 0032_report_ward_rows
Create Date: 2026-11-25

Owner Governance 2026-11-25 (D1; docs/DECISION_LOG.md). Purely additive:

- `borrow_transactions.hn_ciphertext` TEXT NULL: the Fernet token of the HN
  (application-level encryption, key from the host `.env`). NEVER plaintext;
  this migration backfills nothing.
- `borrow_transactions.has_hn` BOOLEAN NOT NULL DEFAULT false: indicator only.
  Existing rows are false.

**Fresh-install vs. historical-upgrade convergence**, following 0023-0031: the
model declares both columns so `0001_initial`'s `create_all()` gives a new
install the same schema as the `IF NOT EXISTS` statements below give a
database that applied 0001-0032; `_verify_schema_convergence()` fails closed
if the two paths disagree. Downgrade drops the columns (and with them every
stored HN -- by design; HN is not recoverable without its key anyway).

Only runs raw SQL against PostgreSQL (dialect-gated like 0002-0031); SQLite
tests build the schema from ORM metadata.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0033_patient_hn"
down_revision: Union[str, None] = "0032_report_ward_rows"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UPGRADE = [
    "ALTER TABLE borrow_transactions ADD COLUMN IF NOT EXISTS hn_ciphertext TEXT",
    "ALTER TABLE borrow_transactions ADD COLUMN IF NOT EXISTS has_hn BOOLEAN NOT NULL DEFAULT false",
]

_DOWNGRADE = [
    "ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS has_hn",
    "ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS hn_ciphertext",
]

# column -> (data_type, is_nullable, default_contains|None)
_EXPECTED = {
    "hn_ciphertext": ("text", "YES", None),
    "has_hn": ("boolean", "NO", "false"),
}


def _verify_schema_convergence() -> None:
    bind = op.get_bind()
    actual = {
        r[0]: r[1:]
        for r in bind.execute(
            sa.text(
                "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'borrow_transactions'"
            )
        ).fetchall()
    }
    for column, (exp_type, exp_nullable, exp_default) in _EXPECTED.items():
        if column not in actual:
            raise RuntimeError(f"borrow_transactions.{column} is missing after this migration.")
        data_type, nullable, default = actual[column]
        if data_type != exp_type or nullable != exp_nullable:
            raise RuntimeError(
                f"borrow_transactions.{column} is {(data_type, nullable)!r}, expected {(exp_type, exp_nullable)!r}."
            )
        if exp_default is None:
            if default is not None:
                raise RuntimeError(f"borrow_transactions.{column} has unexpected default {default!r}.")
        elif default is None or exp_default not in str(default):
            raise RuntimeError(f"borrow_transactions.{column} default is {default!r}, expected {exp_default!r}.")


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
