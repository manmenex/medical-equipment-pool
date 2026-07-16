"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-16

"""
from typing import Sequence, Union

from alembic import op

from app.db.base import Base

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    Base.metadata.create_all(bind=bind)

    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_equipment_name_trgm "
            "ON equipment USING gin (equipment_name gin_trgm_ops)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_equipment_asset_trgm "
            "ON equipment USING gin (asset_number gin_trgm_ops)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_equipment_serial_trgm "
            "ON equipment USING gin (serial_number gin_trgm_ops)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
