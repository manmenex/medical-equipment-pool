"""Export API: hn key scope and hn_update event type (Owner Governance D29)

Revision ID: 0038_export_hn_scope
Revises: 0037_user_ui_preferences
Create Date: 2026-11-27

- `export_api_keys.scope_hn` BOOLEAN NOT NULL DEFAULT false (existing keys stay
  without HN).
- `export_events` event_type CHECK widened to allow 'hn_update'.

Only runs raw SQL against PostgreSQL (dialect-gated like 0002-0037); SQLite
tests build the schema from ORM metadata.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0038_export_hn_scope"
down_revision: Union[str, None] = "0037_user_ui_preferences"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(sa.text("ALTER TABLE export_api_keys ADD COLUMN IF NOT EXISTS scope_hn BOOLEAN NOT NULL DEFAULT false"))
    op.execute(sa.text("ALTER TABLE export_events DROP CONSTRAINT IF EXISTS ck_export_events_event_type"))
    op.execute(
        sa.text(
            "ALTER TABLE export_events ADD CONSTRAINT ck_export_events_event_type "
            "CHECK (event_type IN ('dispatch', 'receipt', 'hn_update'))"
        )
    )
    row = op.get_bind().execute(
        sa.text(
            "SELECT data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'export_api_keys' AND column_name = 'scope_hn'"
        )
    ).fetchone()
    if row is None or tuple(row) != ("boolean", "NO"):
        raise RuntimeError(f"export_api_keys.scope_hn is {row!r}, expected ('boolean', 'NO').")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(sa.text("DELETE FROM export_events WHERE event_type = 'hn_update'"))
    op.execute(sa.text("ALTER TABLE export_events DROP CONSTRAINT IF EXISTS ck_export_events_event_type"))
    op.execute(
        sa.text(
            "ALTER TABLE export_events ADD CONSTRAINT ck_export_events_event_type "
            "CHECK (event_type IN ('dispatch', 'receipt'))"
        )
    )
    op.execute(sa.text("ALTER TABLE export_api_keys DROP COLUMN IF EXISTS scope_hn"))
