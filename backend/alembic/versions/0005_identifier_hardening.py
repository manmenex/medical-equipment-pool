"""retire legacy qr_code_value NOT NULL; enforce ADR-002 canonical BCM Code / Item No storage at the DB level

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
knowledge/architecture/identifiers.md: application-layer normalization
(app/services/identifiers.py) is not sufficient by itself -- a direct SQL
write or a future bulk import could still insert a logical duplicate
("BCM001" vs "bcm001" vs "001") or a non-canonical value that the
application would never produce. This migration adopts the "persist only
canonical values" strategy: convert existing data to its canonical form,
then add a CHECK constraint that *proves* every stored value is already
canonical, so a plain UNIQUE index on the raw column is sufficient for
canonical-form uniqueness -- no functional/expression index needed, and
no way for a non-canonical value to exist in the table at all, regardless
of which code path wrote it.

  - `ck_equipment_bcm_code_canonical`: bcm_code is NULL, or matches
    `^BCM\\S+$` (the literal "BCM" prefix followed by one or more
    non-whitespace characters, nothing else) AND equals its own
    uppercase form. This is the same shape app.services.identifiers.
    normalize_bcm_code produces and nothing else -- in particular, a
    value with whitespace embedded after the prefix (e.g. "BCM 001")
    is rejected, not silently folded into "BCM001": ADR-002 does not
    define that as an equivalence, so this migration does not invent it
    either (see normalize_bcm_code's own docstring for the same
    decision on the application side).
  - `ck_equipment_item_no_canonical`: item_no is NULL, or is non-empty
    and equals its own trimmed form.

Existing `ix_equipment_bcm_code` / `ix_equipment_item_no` (from 0004,
both plain unique indexes) are left exactly as they are -- once the CHECK
constraints guarantee every stored value is already canonical, a plain
per-column UNIQUE index already *is* canonical-form uniqueness. (An
earlier draft of this migration instead replaced ix_equipment_bcm_code
with a functional UPPER(bcm_code) index; that approach is superseded by
the CHECK-constraint strategy above, which is simpler and additionally
catches the prefix-optional and whitespace collision cases a case-folding
functional index alone would not. `DROP INDEX IF EXISTS` on that
now-abandoned index name is kept below purely so a scratch database that
already ran the earlier draft can still re-run this migration cleanly.)

Collision preflight (upgrade): every existing non-null bcm_code and
item_no value is run through the exact same
app.services.identifiers.normalize_bcm_code / normalize_item_no functions
the application uses for every write, so this can never silently drift
from the application's own definition of "canonical." Three distinct
failure modes are reported separately and abort the migration before any
schema change is made, each naming the specific offending row(s):
  1. A value that cannot be normalized at all (empty after the prefix,
     embedded whitespace, or would exceed the column width once
     canonicalized).
  2. Two or more rows whose canonical forms collide (case difference,
     surrounding whitespace, or prefix-present vs. prefix-omitted).
Only after every row passes are existing values actually rewritten to
their canonical form (deterministic, one UPDATE per row that needs it)
and the CHECK constraints added. Nothing is silently merged, dropped, or
guessed.

Downgrade: the two CHECK constraints are dropped unconditionally (no data
loss -- a constraint, not a column). Restoring `qr_code_value NOT NULL`
is only safe if no row has a NULL value; any equipment created after this
migration's upgrade will have one (the application stopped populating
it), so the downgrade checks for this and fails clearly rather than
silently violating the column's own constraint history -- back up and
backfill a value for every affected row before downgrading a database
that has taken writes since this migration ran, or prefer a forward fix
instead. Downgrade does not attempt to un-canonicalize bcm_code/item_no
values back to whatever raw form they originally had -- that original
form is not recoverable, and a canonical value remains a valid value
under the looser pre-0005 schema, so nothing needs reverting there.
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

    from app.core.exceptions import InvalidInputError
    from app.services.identifiers import normalize_bcm_code, normalize_item_no

    def _preflight(column: str, normalize) -> dict:
        rows = bind.execute(
            sa.text(f"SELECT id, asset_number, {column} FROM equipment WHERE {column} IS NOT NULL")
        ).fetchall()

        canonical_by_id: dict = {}
        problems: list[str] = []
        for row_id, asset_number, raw_value in rows:
            try:
                canonical_by_id[row_id] = normalize(raw_value)
            except InvalidInputError as exc:
                problems.append(f"  id={row_id} asset_number={asset_number!r} {column}={raw_value!r}: {exc.message}")

        if problems:
            raise RuntimeError(
                f"Migration 0005 aborted: the following equipment.{column} values cannot be "
                "converted to a canonical form and must be corrected by hand before "
                "re-running this migration:\n" + "\n".join(problems)
            )

        by_canonical: dict = {}
        for row_id, canonical in canonical_by_id.items():
            by_canonical.setdefault(canonical, []).append(str(row_id))
        collisions = {c: ids for c, ids in by_canonical.items() if len(ids) > 1}
        if collisions:
            details = "\n".join(f"  {canonical!r} <- rows {ids}" for canonical, ids in collisions.items())
            raise RuntimeError(
                f"Migration 0005 aborted: existing equipment.{column} values collide once "
                f"canonicalized:\n{details}\nResolve these duplicates by hand (decide which "
                "row keeps the value) before re-running this migration."
            )

        return canonical_by_id

    bcm_canonical = _preflight("bcm_code", normalize_bcm_code)
    item_canonical = _preflight("item_no", normalize_item_no)

    # Deterministic conversion to canonical storage -- only rows whose
    # stored value differs from its own canonical form are touched.
    for row_id, canonical in bcm_canonical.items():
        bind.execute(
            sa.text("UPDATE equipment SET bcm_code = :canonical WHERE id = :id AND bcm_code <> :canonical"),
            {"canonical": canonical, "id": row_id},
        )
    for row_id, canonical in item_canonical.items():
        bind.execute(
            sa.text("UPDATE equipment SET item_no = :canonical WHERE id = :id AND item_no <> :canonical"),
            {"canonical": canonical, "id": row_id},
        )

    op.execute("ALTER TABLE equipment ALTER COLUMN qr_code_value DROP NOT NULL")

    # See module docstring: an earlier draft of this migration created
    # this functional index instead of the CHECK-constraint strategy
    # below -- dropped here only so a scratch database that already ran
    # that draft can re-run this migration cleanly.
    op.execute("DROP INDEX IF EXISTS ix_equipment_bcm_code_canonical")

    op.execute(
        "ALTER TABLE equipment ADD CONSTRAINT ck_equipment_bcm_code_canonical "
        r"CHECK (bcm_code IS NULL OR (bcm_code ~ '^BCM\S+$' AND bcm_code = upper(bcm_code)))"
    )
    op.execute(
        "ALTER TABLE equipment ADD CONSTRAINT ck_equipment_item_no_canonical "
        "CHECK (item_no IS NULL OR (item_no <> '' AND item_no = btrim(item_no)))"
    )


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

    op.execute("ALTER TABLE equipment DROP CONSTRAINT IF EXISTS ck_equipment_item_no_canonical")
    op.execute("ALTER TABLE equipment DROP CONSTRAINT IF EXISTS ck_equipment_bcm_code_canonical")
    op.execute("ALTER TABLE equipment ALTER COLUMN qr_code_value SET NOT NULL")
