"""Ward and department contact phone (Roadmap PR25E slice B0)

Revision ID: 0026_ward_department_phone
Revises: 0025_export_events
Create Date: 2026-10-13

Adds one purely additive, nullable column `phone VARCHAR(20)` to `wards` and
to `departments` (docs/design/PR25D_OFFLINE_OPERATION_PLAN.md section 3.4,
Owner decision D2). No backfill, no default, no existing value rewritten; the
20-character cap matches `borrow_transactions.phone_number`.

**Fresh-install vs. historical-upgrade convergence**, following 0023-0025.
`app.models.master_data` declares both columns, so `0001_initial`'s
`Base.metadata.create_all()` gives a brand-new install the same columns as the
`ADD COLUMN IF NOT EXISTS` statements below give a database that applied
0001-0025. `_verify_schema_convergence()` fails closed if the two paths
disagree on type, length, nullability or catalog default (none is expected).

Only runs raw SQL against PostgreSQL (dialect-gated like 0002-0025); SQLite
tests build the columns from ORM metadata.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026_ward_department_phone"
down_revision: Union[str, None] = "0025_export_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("wards", "departments")

# (data_type, character_maximum_length, is_nullable); no catalog default.
_EXPECTED = ("character varying", 20, "YES")

_COLUMN_SQL = sa.text(
    """
    SELECT data_type, character_maximum_length, is_nullable, column_default
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = :table AND column_name = 'phone'
    """
)


def _verify_schema_convergence() -> None:
    """Fail closed if the historical-upgrade path produced a column the
    fresh-install path would not have."""
    bind = op.get_bind()
    for table in _TABLES:
        row = bind.execute(_COLUMN_SQL, {"table": table}).fetchone()
        if row is None:
            raise RuntimeError(f"{table}.phone is missing after this migration.")
        data_type, max_len, is_nullable, column_default = row
        if (data_type, max_len, is_nullable) != _EXPECTED:
            raise RuntimeError(
                f"{table}.phone is {(data_type, max_len, is_nullable)!r}, expected {_EXPECTED!r}."
            )
        if column_default is not None:
            raise RuntimeError(f"{table}.phone has unexpected catalog default {column_default!r}.")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in _TABLES:
        op.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS phone VARCHAR(20)"))
    _verify_schema_convergence()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in _TABLES:
        op.execute(sa.text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS phone"))
