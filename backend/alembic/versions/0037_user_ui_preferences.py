"""Per-user UI theme preferences (users.ui_preferences)

Revision ID: 0037_user_ui_preferences
Revises: 0036_keyer_labels
Create Date: 2026-11-27

Purely additive: `users.ui_preferences` JSONB NULL, no default, no foreign key.
Holds the account's own theme (mode, colours, font size/family); validated by
the API schema, never contains patient or equipment data.

Only runs raw SQL against PostgreSQL (dialect-gated like 0002-0036); SQLite
tests build the schema from ORM metadata.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0037_user_ui_preferences"
down_revision: Union[str, None] = "0036_keyer_labels"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _verify() -> None:
    row = op.get_bind().execute(
        sa.text(
            "SELECT data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'ui_preferences'"
        )
    ).fetchone()
    if row is None or tuple(row) != ("jsonb", "YES"):
        raise RuntimeError(f"users.ui_preferences is {row!r}, expected ('jsonb', 'YES').")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(sa.text("ALTER TABLE users ADD COLUMN IF NOT EXISTS ui_preferences JSONB"))
    _verify()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(sa.text("ALTER TABLE users DROP COLUMN IF EXISTS ui_preferences"))
