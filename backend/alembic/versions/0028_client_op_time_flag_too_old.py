"""Allow time_flag 'too_old' on client_operations (Roadmap PR25E slice B2b)

Revision ID: 0028_client_op_time_flag_too_old
Revises: 0027_client_operations
Create Date: 2026-10-13

Owner decision D9 (docs/design/PR25D_OFFLINE_OPERATION_PLAN.md sections 11, 18):
an offline op older than 7 days is stored as a conflict with
``time_flag='too_old'``. Only the CHECK constraint is widened; no data changes.
``clamped_old`` stays allowed so any existing row remains valid.

Fresh installs get the constraint from the model via 0001's create_all();
raw SQL here runs on PostgreSQL only (dialect-gated like 0002-0027).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028_client_op_time_flag_too_old"
down_revision: Union[str, None] = "0027_client_operations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NAME = "ck_client_operations_time_flag"
_OLD = "'clamped_future', 'clamped_old', 'before_dispatch', 'before_last_receipt'"
_NEW = _OLD + ", 'too_old'"


def _swap(values: str) -> None:
    op.execute(sa.text(f"ALTER TABLE client_operations DROP CONSTRAINT IF EXISTS {_NAME}"))
    op.execute(
        sa.text(
            f"ALTER TABLE client_operations ADD CONSTRAINT {_NAME} "
            f"CHECK (time_flag IS NULL OR time_flag IN ({values}))"
        )
    )


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        _swap(_NEW)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("UPDATE client_operations SET time_flag = NULL WHERE time_flag = 'too_old'"))
        _swap(_OLD)
