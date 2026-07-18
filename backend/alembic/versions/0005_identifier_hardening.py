"""retire legacy qr_code_value NOT NULL; enforce BCM Code canonical-form uniqueness at the DB level

Revision ID: 0005_identifier_hardening
Revises: 0004_equipment_item_no_bcm_code
Create Date: 2026-07-18

See ADR-004 (knowledge/adr/ADR-004-hospital-item-no-qr.md): the legacy
self-generated `MEP:{asset_number}` QR scheme is retired. The application
no longer generates a value for `qr_code_value` on equipment create (see
app/api/v1/equipment.py::create_equipment), so the column's `NOT NULL`
constraint from 0001_initial would block every future insert -- this
migration drops it. Existing `qr_code_value` values are left untouched
(historical record only; no active endpoint reads this column anymore).

See ADR-002 (knowledge/adr/ADR-002-identifier-model.md) and
knowledge/architecture/identifiers.md: BCM Code's canonical persisted form
is case-insensitive (always stored uppercase, with the "BCM" prefix). The
application now normalizes every write (app/services/identifiers.py), but
0004's plain UNIQUE index on the raw `bcm_code` column only catches
byte-for-byte duplicates -- it would not catch "BCM001" and "bcm001"
coexisting if either were ever written outside the normalized application
path (a direct SQL insert, a future bulk import, a bug). This migration
replaces it with a case-insensitive functional unique index on
`UPPER(bcm_code)`, so canonical-form uniqueness is enforced at the
database level too, not only by the application. Item No's canonical form
preserves case exactly (no folding), so its existing plain unique index
(`ix_equipment_item_no`, from 0004) is already exactly canonical-form
uniqueness and is left unchanged here.

Collision detection: if any pre-existing rows already collide once
canonicalized (case-insensitively) -- which should not happen for a
never-yet-released Draft feature, but is checked rather than assumed --
this migration fails with a clear error identifying the colliding
canonical value instead of silently creating a broken index or
merging/dropping data. Resolve any reported collision by hand (decide
which row keeps the code) before re-running this migration.

Downgrade: restoring `qr_code_value NOT NULL` is only safe if no row has
a NULL value. Any equipment created after this migration's upgrade will
have one (the application stopped populating it), so the downgrade checks
for this and fails clearly rather than silently violating the column's
own constraint history -- back up and backfill a value for every affected
row before downgrading a database that has taken writes since this
migration ran, or prefer a forward fix instead. The BCM Code functional
index is reverted to 0004's plain form unconditionally (an index change
carries no data-loss risk either direction).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_identifier_hardening"
down_revision: Union[str, None] = "0004_equipment_item_no_bcm_code"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        # Migrations only ever run against PostgreSQL in this project (see
        # 0002/0003/0004's identical branch) -- the SQLite test/dev path
        # builds its schema via Base.metadata.create_all() directly from
        # the ORM models, which already reflect qr_code_value's nullable
        # column. Nothing to do for any other dialect.
        return

    collisions = bind.execute(
        sa.text(
            "SELECT UPPER(bcm_code) AS canonical, count(*) "
            "FROM equipment WHERE bcm_code IS NOT NULL "
            "GROUP BY UPPER(bcm_code) HAVING count(*) > 1"
        )
    ).fetchall()
    if collisions:
        values = ", ".join(row[0] for row in collisions)
        raise RuntimeError(
            "Migration 0005 aborted: existing equipment.bcm_code values collide once "
            f"canonicalized (case-insensitively): {values}. Resolve these duplicates by hand "
            "(decide which row keeps the code) before re-running this migration."
        )

    op.execute("ALTER TABLE equipment ALTER COLUMN qr_code_value DROP NOT NULL")
    op.execute("DROP INDEX IF EXISTS ix_equipment_bcm_code")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_equipment_bcm_code_canonical ON equipment (UPPER(bcm_code))")


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    null_count = bind.execute(sa.text("SELECT count(*) FROM equipment WHERE qr_code_value IS NULL")).scalar_one()
    if null_count:
        raise RuntimeError(
            f"Migration 0005 downgrade aborted: {null_count} equipment row(s) have a NULL "
            "qr_code_value, which would violate the restored NOT NULL constraint. This database "
            "has taken writes since 0005's upgrade (the application no longer populates "
            "qr_code_value on create). Back up and backfill a value for every affected row by "
            "hand before downgrading, or prefer a forward fix instead."
        )

    op.execute("DROP INDEX IF EXISTS ix_equipment_bcm_code_canonical")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_equipment_bcm_code ON equipment (bcm_code)")
    op.execute("ALTER TABLE equipment ALTER COLUMN qr_code_value SET NOT NULL")
