"""add equipment item_no and bcm_code identifier columns

Revision ID: 0004_equipment_item_no_bcm_code
Revises: 0003_transaction_no_seq
Create Date: 2026-07-17

Roadmap PR5 (docs/kickoffs/PR5-equipment-master-bcm-search.md): the two
confirmed Equipment Master identifiers.

  - item_no: the hospital's existing physical QR label content. Internal
    QR-resolution key only.
  - bcm_code: the primary operator-facing identifier; the only field the
    manual-search endpoint matches against.

This migration is purely additive and non-destructive: it adds two nullable
columns to the existing `equipment` table and their supporting indexes. No
existing table, column, or row is touched, dropped, or altered, and no
existing equipment or transaction data is affected. Both columns are
nullable because existing equipment predates them -- the intended backfill
path is a future controlled Excel import (Roadmap PR8), not a mechanical
default or an invented placeholder value here.

A standard UNIQUE constraint (via a unique index, same as every other
unique column in this schema) permits multiple NULLs in both PostgreSQL and
SQLite, so unmigrated equipment rows -- which all start out NULL in both
columns -- do not collide with each other or block this migration.

IF NOT EXISTS everywhere (same pattern as 0002_audit_request_ids.py, see its
docstring): 0001_initial's create_all() reflects whatever the ORM models
look like *at the time it runs*, not a frozen snapshot from when 0001 was
written -- so on a brand-new database, 0001 already creates item_no/
bcm_code (they're part of the current Equipment model), and a plain ADD
COLUMN/CREATE INDEX here would fail as a duplicate. IF NOT EXISTS makes
this migration correct both for that fresh-database case and for an
existing pre-PR5 database catching up.

Indexes:
  - `ix_equipment_item_no` (unique btree): exact-match QR-resolution
    lookups (app.crud.equipment.get_by_item_no) never need more than
    equality, and the column must stay globally unique per the confirmed
    identifier rules.
  - `ix_equipment_bcm_code` (unique btree): exact-match lookups and the
    uniqueness constraint itself.
  - `idx_equipment_bcm_trgm` (PostgreSQL only, GIN trigram): the manual BCM
    search's partial ILIKE '%token%' matching needs this to stay responsive
    against a multi-thousand-row table -- a plain btree index cannot
    accelerate a leading-wildcard LIKE. Uses the same `pg_trgm` extension
    already enabled by migration 0001 (idx_equipment_name_trgm et al.), so
    this introduces no new infrastructure dependency.

Like 0002, this migration is a no-op on any non-PostgreSQL dialect (see the
`else` branch below): migrations only ever run against PostgreSQL in this
project (the SQLite test/dev path builds its schema via
Base.metadata.create_all() directly from the ORM models, which already
include these columns).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_equipment_item_no_bcm_code"
down_revision: Union[str, None] = "0003_transaction_no_seq"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE equipment ADD COLUMN IF NOT EXISTS item_no VARCHAR(64)")
        op.execute("ALTER TABLE equipment ADD COLUMN IF NOT EXISTS bcm_code VARCHAR(64)")
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_equipment_item_no ON equipment (item_no)")
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_equipment_bcm_code ON equipment (bcm_code)")
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_equipment_bcm_trgm "
            "ON equipment USING gin (bcm_code gin_trgm_ops)"
        )
    else:
        # Migrations only ever run against PostgreSQL in this project (the
        # SQLite test/dev path never runs Alembic at all -- see 0002/0003's
        # identical branch), so a plain add_column is a reasonable
        # fallback for any other dialect.
        op.add_column("equipment", sa.Column("item_no", sa.String(length=64), nullable=True))
        op.add_column("equipment", sa.Column("bcm_code", sa.String(length=64), nullable=True))
        op.create_index("ix_equipment_item_no", "equipment", ["item_no"], unique=True)
        op.create_index("ix_equipment_bcm_code", "equipment", ["bcm_code"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS idx_equipment_bcm_trgm")
        op.execute("DROP INDEX IF EXISTS ix_equipment_bcm_code")
        op.execute("DROP INDEX IF EXISTS ix_equipment_item_no")
        op.execute("ALTER TABLE equipment DROP COLUMN IF EXISTS bcm_code")
        op.execute("ALTER TABLE equipment DROP COLUMN IF EXISTS item_no")
    else:
        op.drop_index("ix_equipment_bcm_code", table_name="equipment")
        op.drop_index("ix_equipment_item_no", table_name="equipment")
        op.drop_column("equipment", "bcm_code")
        op.drop_column("equipment", "item_no")
