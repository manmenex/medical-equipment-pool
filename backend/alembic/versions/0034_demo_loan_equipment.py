"""Demo/loan equipment, serial number as BCM Code, return to owner (Roadmap PR33)

Revision ID: 0034_demo_loan_equipment
Revises: 0033_patient_hn
Create Date: 2026-11-26

Owner Governance 2026-11-26 (D14; docs/DECISION_LOG.md). Additive columns on
`equipment` plus one deliberate constraint change:

- `equipment_source` VARCHAR(10) NOT NULL DEFAULT 'pool' (pool|demo|loan, with
  a CHECK) -- every existing row becomes 'pool'.
- `owner_company` VARCHAR(255) NULL, `due_back_date` DATE NULL.
- `has_charger` / `has_clamp` BOOLEAN NOT NULL DEFAULT true.
- `returned_to_owner_at` TIMESTAMPTZ NULL, `returned_to_owner_by_user_id`
  UUID NULL (FK users, RESTRICT). A flag, not a fifth equipment state.
- `ck_equipment_bcm_code_canonical` (0005) is replaced by a constraint of the
  same name that applies the canonical-form rule to `pool` rows only: for
  demo/loan devices `bcm_code` holds the manufacturer Serial Number (narrow
  amendment to ADR-002; identifier count and roles unchanged). Uniqueness is
  unchanged (the plain unique index still covers every row).

Downgrade removes the columns and restores the original constraint; it
FAILS CLOSED (aborts) if any demo/loan row exists, because its serial-number
`bcm_code` cannot satisfy the pool canonical rule and silently deleting
equipment history is not acceptable.

Dialect-gated like 0002-0033: SQLite tests build the schema from ORM metadata.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0034_demo_loan_equipment"
down_revision: Union[str, None] = "0033_patient_hn"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UPGRADE = [
    "ALTER TABLE equipment ADD COLUMN IF NOT EXISTS equipment_source VARCHAR(10) NOT NULL DEFAULT 'pool'",
    "ALTER TABLE equipment ADD COLUMN IF NOT EXISTS owner_company VARCHAR(255)",
    "ALTER TABLE equipment ADD COLUMN IF NOT EXISTS due_back_date DATE",
    "ALTER TABLE equipment ADD COLUMN IF NOT EXISTS has_charger BOOLEAN NOT NULL DEFAULT true",
    "ALTER TABLE equipment ADD COLUMN IF NOT EXISTS has_clamp BOOLEAN NOT NULL DEFAULT true",
    "ALTER TABLE equipment ADD COLUMN IF NOT EXISTS returned_to_owner_at TIMESTAMP WITH TIME ZONE",
    "ALTER TABLE equipment ADD COLUMN IF NOT EXISTS returned_to_owner_by_user_id UUID "
    "REFERENCES users(id) ON DELETE RESTRICT",
    "CREATE INDEX IF NOT EXISTS ix_equipment_equipment_source ON equipment (equipment_source)",
    "ALTER TABLE equipment DROP CONSTRAINT IF EXISTS ck_equipment_equipment_source",
    "ALTER TABLE equipment ADD CONSTRAINT ck_equipment_equipment_source "
    "CHECK (equipment_source IN ('pool', 'demo', 'loan'))",
    "ALTER TABLE equipment DROP CONSTRAINT IF EXISTS ck_equipment_bcm_code_canonical",
    "ALTER TABLE equipment ADD CONSTRAINT ck_equipment_bcm_code_canonical "
    r"CHECK (bcm_code IS NULL OR equipment_source <> 'pool' "
    r"OR (bcm_code ~ '^BCM\S+$' AND bcm_code = upper(bcm_code)))",
]

_DOWNGRADE = [
    "ALTER TABLE equipment DROP CONSTRAINT IF EXISTS ck_equipment_bcm_code_canonical",
    "ALTER TABLE equipment ADD CONSTRAINT ck_equipment_bcm_code_canonical "
    r"CHECK (bcm_code IS NULL OR (bcm_code ~ '^BCM\S+$' AND bcm_code = upper(bcm_code)))",
    "ALTER TABLE equipment DROP CONSTRAINT IF EXISTS ck_equipment_equipment_source",
    "DROP INDEX IF EXISTS ix_equipment_equipment_source",
    "ALTER TABLE equipment DROP COLUMN IF EXISTS returned_to_owner_by_user_id",
    "ALTER TABLE equipment DROP COLUMN IF EXISTS returned_to_owner_at",
    "ALTER TABLE equipment DROP COLUMN IF EXISTS has_clamp",
    "ALTER TABLE equipment DROP COLUMN IF EXISTS has_charger",
    "ALTER TABLE equipment DROP COLUMN IF EXISTS due_back_date",
    "ALTER TABLE equipment DROP COLUMN IF EXISTS owner_company",
    "ALTER TABLE equipment DROP COLUMN IF EXISTS equipment_source",
]

# column -> (data_type, is_nullable, default_contains|None)
_EXPECTED = {
    "equipment_source": ("character varying", "NO", "pool"),
    "owner_company": ("character varying", "YES", None),
    "due_back_date": ("date", "YES", None),
    "has_charger": ("boolean", "NO", "true"),
    "has_clamp": ("boolean", "NO", "true"),
    "returned_to_owner_at": ("timestamp with time zone", "YES", None),
    "returned_to_owner_by_user_id": ("uuid", "YES", None),
}


def _verify_schema_convergence() -> None:
    bind = op.get_bind()
    actual = {
        r[0]: r[1:]
        for r in bind.execute(
            sa.text(
                "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'equipment'"
            )
        ).fetchall()
    }
    for column, (exp_type, exp_nullable, exp_default) in _EXPECTED.items():
        if column not in actual:
            raise RuntimeError(f"equipment.{column} is missing after this migration.")
        data_type, nullable, default = actual[column]
        if data_type != exp_type or nullable != exp_nullable:
            raise RuntimeError(
                f"equipment.{column} is {(data_type, nullable)!r}, expected {(exp_type, exp_nullable)!r}."
            )
        if exp_default is None:
            if default is not None:
                raise RuntimeError(f"equipment.{column} has unexpected default {default!r}.")
        elif default is None or exp_default not in str(default):
            raise RuntimeError(f"equipment.{column} default is {default!r}, expected {exp_default!r}.")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for statement in _UPGRADE:
        op.execute(sa.text(statement))
    _verify_schema_convergence()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    count = bind.execute(sa.text("SELECT count(*) FROM equipment WHERE equipment_source <> 'pool'")).scalar_one()
    if count:
        raise RuntimeError(
            f"Cannot downgrade 0034: {count} demo/loan equipment row(s) exist; their serial-number bcm_code "
            "values would violate the pool canonical constraint. Remove or convert them first."
        )
    for statement in _DOWNGRADE:
        op.execute(sa.text(statement))
