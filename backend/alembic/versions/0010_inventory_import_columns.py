"""add equipment.asset_id, equipment.raw_source_status (Roadmap PR12)

Revision ID: 0010_inventory_import_columns
Revises: 0009_role_consolidation
Create Date: 2026-07-26

Roadmap PR12 (docs/audits/04-consolidated-implementation-plan.md Part D
"PR12 -- Inventory import"; Part E's migration table, row "Add Asset ID";
Part F "Inventory Import Plan", §F.1 step 3): the inventory import
workflow's design explicitly calls for two columns that do not exist yet
on `equipment` --

  - asset_id            new, nullable, optional metadata distinct from
                         the existing `asset_number` column (Part E:
                         "asset_number remains a separate, retained
                         metadata field ... not renamed, reused, or
                         merged into either identifier column"). Sourced
                         from the import file's "Asset ID" header.
                         Uniqueness is explicitly "pending hospital
                         confirmation" (§14 open question 2) -- this
                         migration adds a plain, non-unique index for
                         duplicate-detection query performance only, not
                         a UNIQUE constraint. Import-side duplicate
                         detection is therefore conservative and
                         application-layer only (see
                         app.services.import_service): flagged at row
                         level, never silently overwritten, and never
                         used as the match key for an existing equipment
                         record (BCM Code remains that key).
  - raw_source_status   new, nullable. Preserves the import file's
                         "Asset Status" column value verbatim, before
                         that value is mapped into the confirmed 4-state
                         EquipmentStatus model through the explicit,
                         approved mapping table in Part F.2 (illustrative
                         pending a real hospital inventory export --
                         §14 open question 4). An unrecognized source
                         value is a per-row import failure, never a
                         guess, and never persisted as a status
                         directly -- raw_source_status exists purely so
                         the as-imported source value is auditable
                         later, independent of the mapping table's
                         current contents.

Both columns are purely additive (nullable, no CHECK, no NOT NULL, no
backfill) -- every existing row trivially satisfies them (NULL), so this
migration has no preflight-abort path, mirroring migration 0008's
dispatch_type/routine_round precedent. This migration does NOT import
app.models.equipment or any other runtime application module (PR5-H3R-MIG
/ 0006-0009's identical convention): column widths are chosen and frozen
locally at this revision.

Downgrade: drops both columns. Fully reversible with no data loss for any
row created before this migration (both were always NULL); a forward fix
is preferred over downgrading a database that has already run a real
import, since asset_id/raw_source_status values written after upgrade
would be silently discarded by a downgrade -- consistent with this
project's general migration philosophy (see Part E's "additive-first"
rule) but, unlike migration 0008's borrower_name restore, dropping an
already-nullable column can never fail a precondition check, so no
preflight guard is needed here.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0010_inventory_import_columns"
down_revision: Union[str, None] = "0009_role_consolidation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        # Migrations only ever run against PostgreSQL in this project (see
        # 0002-0009's identical branch) -- the SQLite test/dev path builds
        # its schema via Base.metadata.create_all() directly from the ORM
        # models, which already reflect these columns. Nothing to do for
        # any other dialect.
        return

    op.execute("ALTER TABLE equipment ADD COLUMN IF NOT EXISTS asset_id VARCHAR(100)")
    op.execute("ALTER TABLE equipment ADD COLUMN IF NOT EXISTS raw_source_status VARCHAR(100)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_equipment_asset_id ON equipment (asset_id)")


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_equipment_asset_id")
    op.execute("ALTER TABLE equipment DROP COLUMN IF EXISTS raw_source_status")
    op.execute("ALTER TABLE equipment DROP COLUMN IF EXISTS asset_id")
