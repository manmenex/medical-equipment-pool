"""add request_id and correlation_id to audit_logs

Revision ID: 0002_audit_request_ids
Revises: 0001_initial
Create Date: 2026-07-16

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_audit_request_ids"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        # 0001_initial's create_all() reflects whatever the ORM models look
        # like *at the time it runs*, not a frozen snapshot from when 0001
        # was written — so on a brand-new database, 0001 already creates
        # these columns (they're part of the current AuditLog model), and a
        # plain ADD COLUMN here would fail as a duplicate. IF NOT EXISTS
        # makes this migration correct both for that fresh-database case and
        # for any database that ran 0001 before these columns were added to
        # the model (the case this migration exists for).
        op.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS request_id VARCHAR(64)")
        op.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS correlation_id VARCHAR(64)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_audit_logs_request_id ON audit_logs (request_id)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_audit_logs_correlation_id ON audit_logs (correlation_id)")
    else:
        # Migrations only ever run against PostgreSQL in this project (the
        # test suite builds its schema via Base.metadata.create_all()
        # directly — see backend/tests/conftest.py), so a plain add_column
        # is a reasonable fallback for any other dialect.
        op.add_column("audit_logs", sa.Column("request_id", sa.String(length=64), nullable=True))
        op.add_column("audit_logs", sa.Column("correlation_id", sa.String(length=64), nullable=True))
        op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"])
        op.create_index("ix_audit_logs_correlation_id", "audit_logs", ["correlation_id"])


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_audit_logs_correlation_id")
        op.execute("DROP INDEX IF EXISTS ix_audit_logs_request_id")
        op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS correlation_id")
        op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS request_id")
    else:
        op.drop_index("ix_audit_logs_correlation_id", table_name="audit_logs")
        op.drop_index("ix_audit_logs_request_id", table_name="audit_logs")
        op.drop_column("audit_logs", "correlation_id")
        op.drop_column("audit_logs", "request_id")
