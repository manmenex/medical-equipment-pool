"""Asset Number becomes optional: equipment.asset_number nullable (Governance 2026-10-21)

Revision ID: 0029_asset_number_optional
Revises: 0028_client_op_time_flag_too_old
Create Date: 2026-10-21

Owner decision (docs/DECISION_LOG.md, Governance 2026-10-21; ADR-002
amendment): Asset Number is OPTIONAL. Equipment may exist without one; the
value is never fabricated or derived (never copied from `asset_id`). Only
the NOT NULL constraint is dropped. The UNIQUE index
`ix_equipment_asset_number` is kept as is: PostgreSQL treats NULLs as
distinct in a unique index, so any number of rows may have no Asset Number
while every non-NULL value stays unique.

**Fresh-install vs. historical-upgrade convergence**, following 0023-0028.
`app.models.equipment` declares the column `nullable=True`, so
`0001_initial`'s `Base.metadata.create_all()` gives a brand-new install the
same column the `DROP NOT NULL` below gives a database that applied
0001-0028. `_verify_schema_convergence()` fails closed if the two paths
disagree on type, length, nullability, catalog default, or the unique index.

**Downgrade** restores NOT NULL, which is impossible while any row has no
Asset Number. It refuses (raises) rather than fabricating placeholder values;
an operator must assign real Asset Numbers (or remove those rows) first.

Only runs raw SQL against PostgreSQL (dialect-gated like 0002-0028); SQLite
tests build the column from ORM metadata.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029_asset_number_optional"
down_revision: Union[str, None] = "0028_client_op_time_flag_too_old"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX = "ix_equipment_asset_number"

_COLUMN_SQL = sa.text(
    """
    SELECT data_type, character_maximum_length, is_nullable, column_default
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'equipment' AND column_name = 'asset_number'
    """
)
_INDEX_SQL = sa.text(
    "SELECT indexdef FROM pg_indexes "
    "WHERE schemaname = 'public' AND tablename = 'equipment' AND indexname = :name"
)


def _verify_schema_convergence() -> None:
    """Fail closed if the historical-upgrade path produced a column the
    fresh-install path would not have."""
    bind = op.get_bind()
    row = bind.execute(_COLUMN_SQL).fetchone()
    if row is None:
        raise RuntimeError("equipment.asset_number is missing after this migration.")
    data_type, max_len, is_nullable, column_default = row
    expected = ("character varying", 50, "YES")
    if (data_type, max_len, is_nullable) != expected:
        raise RuntimeError(f"equipment.asset_number is {(data_type, max_len, is_nullable)!r}, expected {expected!r}.")
    if column_default is not None:
        raise RuntimeError(f"equipment.asset_number has unexpected catalog default {column_default!r}.")
    index = bind.execute(_INDEX_SQL, {"name": _INDEX}).fetchone()
    if index is None or "UNIQUE" not in index[0].upper():
        raise RuntimeError(f"{_INDEX} must exist and be UNIQUE after this migration.")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(sa.text("ALTER TABLE equipment ALTER COLUMN asset_number DROP NOT NULL"))
    _verify_schema_convergence()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    missing = bind.execute(sa.text("SELECT count(*) FROM equipment WHERE asset_number IS NULL")).scalar_one()
    if missing:
        raise RuntimeError(
            f"Cannot downgrade 0029: {missing} equipment row(s) have no Asset Number and the previous schema "
            "requires one. Asset Numbers are never fabricated -- assign real values or remove those rows first."
        )
    op.execute(sa.text("ALTER TABLE equipment ALTER COLUMN asset_number SET NOT NULL"))
