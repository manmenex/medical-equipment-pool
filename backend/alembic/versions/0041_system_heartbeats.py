"""System heartbeats for the admin health banner

Revision ID: 0041_system_heartbeats
Revises: 0040_export_corrections
Create Date: 2026-11-28

Adds `system_heartbeats(key, beat_at)`: the legacy sheet sync runner records
its last successful pass here. Dialect-gated like 0002-0040.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0041_system_heartbeats"
down_revision: Union[str, None] = "0040_export_corrections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(sa.text(
        "CREATE TABLE IF NOT EXISTS system_heartbeats ("
        "key VARCHAR(64) PRIMARY KEY, beat_at TIMESTAMPTZ NOT NULL)"
    ))


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(sa.text("DROP TABLE IF EXISTS system_heartbeats"))
