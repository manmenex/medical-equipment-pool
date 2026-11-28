"""Non-blocking dispatch columns on borrow_transactions (Roadmap PR31, D8)

Revision ID: 0030_non_blocking_dispatch
Revises: 0029_asset_number_optional
Create Date: 2026-11-25

Owner Governance 2026-11-25, second set (D8; docs/DECISION_LOG.md): dispatch
is no longer blocked by equipment status. Two purely additive columns on
`borrow_transactions` record what the dispatch service did:

- `close_reason VARCHAR(100) NULL`: set only on a transaction the dispatch
  service closed by re-dispatching the same equipment ("closed by
  re-dispatch, receipt not recorded"). Such a row is CLOSED with
  `returned_at`, `condition_on_return` and `received_by_user_id` all NULL --
  no receipt is ever fabricated. NULL for every historical row and for every
  ordinarily received transaction.
- `dispatched_while_defective BOOLEAN NOT NULL DEFAULT false`: true on a
  transaction opened while the equipment was `unavailable_defective`
  (operator confirmed). Existing rows backfill to false through the default.

**Fresh-install vs. historical-upgrade convergence**, following 0023-0029.
`app.models.transaction` declares both columns (the Boolean with
`server_default=false()`), so `0001_initial`'s `create_all()` gives a new
install the same columns as the `ADD COLUMN IF NOT EXISTS` below.
`_verify_schema_convergence()` fails closed if the two paths disagree.

Only runs raw SQL against PostgreSQL (dialect-gated like 0002-0029); SQLite
tests build the columns from ORM metadata.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0030_non_blocking_dispatch"
down_revision: Union[str, None] = "0029_asset_number_optional"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMN_SQL = sa.text(
    """
    SELECT data_type, character_maximum_length, is_nullable, column_default
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'borrow_transactions' AND column_name = :name
    """
)


def _verify_schema_convergence() -> None:
    bind = op.get_bind()
    close_reason = bind.execute(_COLUMN_SQL, {"name": "close_reason"}).fetchone()
    if close_reason is None or tuple(close_reason[:3]) != ("character varying", 100, "YES"):
        raise RuntimeError(f"borrow_transactions.close_reason is {close_reason!r} after this migration.")
    if close_reason[3] is not None:
        raise RuntimeError(f"borrow_transactions.close_reason has unexpected default {close_reason[3]!r}.")
    flag = bind.execute(_COLUMN_SQL, {"name": "dispatched_while_defective"}).fetchone()
    if flag is None or flag[0] != "boolean" or flag[2] != "NO" or flag[3] != "false":
        raise RuntimeError(f"borrow_transactions.dispatched_while_defective is {flag!r} after this migration.")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(sa.text("ALTER TABLE borrow_transactions ADD COLUMN IF NOT EXISTS close_reason VARCHAR(100)"))
    op.execute(
        sa.text(
            "ALTER TABLE borrow_transactions "
            "ADD COLUMN IF NOT EXISTS dispatched_while_defective BOOLEAN NOT NULL DEFAULT false"
        )
    )
    _verify_schema_convergence()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(sa.text("ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS dispatched_while_defective"))
    op.execute(sa.text("ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS close_reason"))
