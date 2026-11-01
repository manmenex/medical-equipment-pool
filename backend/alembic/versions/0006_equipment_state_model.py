"""collapse the 8-value equipment status enum to the confirmed 4-state model

Revision ID: 0006_equipment_state_model
Revises: 0005_identifier_hardening
Create Date: 2026-07-19

Roadmap PR6 (docs/audits/04-consolidated-implementation-plan.md, Part D):
replaces the legacy 8-value `equipment.status` domain (available, borrowed,
cleaning, pm, calibration, repair, out_of_service, lost) with the confirmed
4-state model from `HOSPITAL_DOMAIN_MODEL.md`:

  - available_at_pool
  - issued_to_ward
  - unavailable_defective
  - decommissioned

Every remapped row's original pre-migration value is preserved verbatim in
a new nullable `legacy_status` column -- historical/rollback metadata only,
never read by any workflow, eligibility check, or dispatch decision (See
AGENTS.md's cleaning-retirement guardrail and
app.crud.equipment.change_status, which never references it).

PR5-H3R-MIG-style immutability: this migration does NOT import
app.models.equipment, app.core.exceptions, or any other runtime application
module. The legacy-to-target mapping and the four-state target set are
defined locally, frozen at this revision, so a later PR renaming or
re-scoping EquipmentStatus can never change what this migration already did
to a real database.

Owner-confirmed cleaning retirement (this Roadmap PR6 task; supersedes the
Part E / Part I / §14-item-6 draft language in
docs/audits/04-consolidated-implementation-plan.md that proposed routing
`cleaning` through `UNAVAILABLE_DEFECTIVE` pending manual review -- see the
narrow correction made to that document alongside this migration):
cleaning is performed as part of collecting/receiving equipment, not a
separately tracked state. A legacy `cleaning` row is data proving the
device was already collected and (per the confirmed hospital workflow)
cleaned and checked, i.e. exactly the state `available_at_pool` describes.
Mapping it there is not a guess or a defect classification -- it is the
literal, correct target state for that historical value. This migration
must NOT map `cleaning` to `unavailable_defective`, must NOT flag it for
manual review, and must NOT emit any warning/report distinguishing it from
any other `available_at_pool` row -- `legacy_status='cleaning'` remains
visible only as ordinary historical/rollback metadata, on equal footing
with every other preserved legacy value.

Legacy-to-target mapping (exhaustive -- see LEGACY_STATUS_MAP below):

  available      -> available_at_pool
  borrowed       -> issued_to_ward
  cleaning       -> available_at_pool   (owner-confirmed retirement, above)
  out_of_service -> unavailable_defective
  lost           -> unavailable_defective
  pm             -> unavailable_defective
  calibration    -> unavailable_defective
  repair         -> unavailable_defective

Preflight (upgrade): every distinct existing `status` value is checked
against LEGACY_STATUS_MAP's keys, with one exception -- a value that is
already one of the four target states is left untouched and does not
receive a `legacy_status` (this makes the migration safe to run against a
database whose `equipment` table was created fresh via
`Base.metadata.create_all()` at 0001, which already reflects today's
4-state default and already has a `legacy_status` column -- see 0004's
docstring for why 0001 behaves this way). Any OTHER distinct value aborts
the migration before any row is written, naming every unexpected value and
its row count -- never a guess, never a partial remap.

Verification (upgrade): row count unchanged; no row is left with a NULL
`status`; every `status` value belongs to the four-state target set; every
row whose `status` changed carries its exact original value in
`legacy_status`; every `cleaning` row specifically now reads
`status='available_at_pool', legacy_status='cleaning'`.

Constraint timing: `ck_equipment_status_four_state` (CHECK) is added only
after the verification above passes, so a database that fails preflight or
verification is left with no new constraint and no partially-remapped data
(the whole migration runs inside Alembic's transactional DDL).

Downgrade: aborts cleanly, with no partial restoration, if any row has a
NULL `legacy_status` -- such a row was created after this migration's
upgrade (the 4-state-only application no longer writes an 8-state legacy
value), so there is no original value to reconstruct and guessing one would
corrupt data. If every row has a `legacy_status`, the CHECK constraint is
dropped, `status` is restored from `legacy_status` for every row
(byte-for-byte, including `cleaning`), and the `legacy_status` column
itself is then dropped -- symmetric with 0004's downgrade convention for a
column this migration purely added. Prefer a forward fix over downgrading a
database that has taken real writes since this migration's upgrade.

At the confirmed MVP scale (low hundreds of equipment rows), this migration
is expected to complete in well under a second; see the PR6 evidence table
in the Draft PR description for actual row-count timing from this
migration's test run.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_equipment_state_model"
down_revision: Union[str, None] = "0005_identifier_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Revision-local, frozen mapping. See the immutability note in this module's
# docstring -- deliberately NOT imported from app.models.equipment.
# ---------------------------------------------------------------------------

_LEGACY_STATUS_VALUES: dict[str, str] = {
    "available": "available_at_pool",
    "borrowed": "issued_to_ward",
    "cleaning": "available_at_pool",
    "out_of_service": "unavailable_defective",
    "lost": "unavailable_defective",
    "pm": "unavailable_defective",
    "calibration": "unavailable_defective",
    "repair": "unavailable_defective",
}

# Every equipment row ever created through POST /equipment used the ORM
# column default (status is not a client-settable create field), never an
# explicit raw value -- and app.models.equipment.EquipmentStatusType, before
# this same Roadmap PR6 fixed it with values_callable, bound each Python
# enum member by its *name* (e.g. "AVAILABLE"), not its intended lowercase
# .value ("available"). So a real pre-PR6 database is expected to hold the
# uppercase legacy *names* (AVAILABLE, BORROWED, CLEANING, PM, CALIBRATION,
# REPAIR, OUT_OF_SERVICE, LOST), not the lowercase values -- both forms are
# therefore accepted as legitimate legacy data and map to the exact same
# target, so this migration does not abort on real data caused by that
# now-fixed bug. See app/models/equipment.py's EquipmentStatusType comment.
LEGACY_STATUS_MAP: dict[str, str] = {
    **_LEGACY_STATUS_VALUES,
    **{legacy.upper(): target for legacy, target in _LEGACY_STATUS_VALUES.items()},
}

TARGET_STATUSES: tuple[str, ...] = (
    "available_at_pool",
    "issued_to_ward",
    "unavailable_defective",
    "decommissioned",
)


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        # Migrations only ever run against PostgreSQL in this project (see
        # 0002/0003/0004/0005's identical branch) -- the SQLite test/dev
        # path builds its schema via Base.metadata.create_all() directly
        # from the ORM models, which already reflect the 4-state default
        # and the legacy_status column. Nothing to do for any other
        # dialect.
        return

    op.execute("ALTER TABLE equipment ADD COLUMN IF NOT EXISTS legacy_status VARCHAR(30)")

    before_count = bind.execute(sa.text("SELECT count(*) FROM equipment")).scalar_one()

    rows = bind.execute(sa.text("SELECT status, count(*) FROM equipment GROUP BY status")).fetchall()
    distinct_statuses = {row[0] for row in rows}
    counts_by_status = {row[0]: row[1] for row in rows}

    target_set = set(TARGET_STATUSES)
    unexpected = distinct_statuses - set(LEGACY_STATUS_MAP.keys()) - target_set
    if unexpected:
        details = "\n".join(
            f"  {value!r}: {counts_by_status[value]} row(s)" for value in sorted(unexpected)
        )
        raise RuntimeError(
            "Migration 0006 aborted: the following unexpected equipment.status values were "
            "found and have no approved mapping to the 4-state model. Resolve these by hand "
            "(correct the data or extend the approved mapping in a new migration) before "
            "re-running this migration -- nothing has been remapped:\n" + details
        )

    # Deterministic, one UPDATE per legacy source value actually present.
    # Values already in the target set (a fresh database created via
    # 0001's create_all(), see module docstring) are left untouched --
    # no legacy_status is invented for them.
    for legacy_value, target_value in LEGACY_STATUS_MAP.items():
        if legacy_value not in counts_by_status:
            continue
        bind.execute(
            sa.text(
                "UPDATE equipment SET legacy_status = status, status = :target WHERE status = :legacy"
            ),
            {"target": target_value, "legacy": legacy_value},
        )

    after_count = bind.execute(sa.text("SELECT count(*) FROM equipment")).scalar_one()
    if after_count != before_count:
        raise RuntimeError(
            f"Migration 0006 aborted: row count changed during remap ({before_count} -> {after_count}); "
            "no constraint has been added."
        )

    null_status_count = bind.execute(
        sa.text("SELECT count(*) FROM equipment WHERE status IS NULL")
    ).scalar_one()
    if null_status_count:
        raise RuntimeError(
            f"Migration 0006 aborted: {null_status_count} row(s) have a NULL status after remap; "
            "no constraint has been added."
        )

    non_target_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM equipment WHERE status NOT IN "
            "('available_at_pool', 'issued_to_ward', 'unavailable_defective', 'decommissioned')"
        )
    ).scalar_one()
    if non_target_count:
        raise RuntimeError(
            f"Migration 0006 aborted: {non_target_count} row(s) have a status outside the 4-state "
            "target set after remap; no constraint has been added."
        )

    for legacy_value, target_value in LEGACY_STATUS_MAP.items():
        expected = counts_by_status.get(legacy_value, 0)
        if expected == 0:
            continue
        actual = bind.execute(
            sa.text(
                "SELECT count(*) FROM equipment WHERE status = :target AND legacy_status = :legacy"
            ),
            {"target": target_value, "legacy": legacy_value},
        ).scalar_one()
        if actual != expected:
            raise RuntimeError(
                f"Migration 0006 aborted: expected {expected} row(s) remapped from {legacy_value!r} to "
                f"{target_value!r} with legacy_status preserved, found {actual}; no constraint has been added."
            )

    op.execute(
        "ALTER TABLE equipment ADD CONSTRAINT ck_equipment_status_four_state "
        "CHECK (status IN ('available_at_pool', 'issued_to_ward', 'unavailable_defective', 'decommissioned'))"
    )


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    null_legacy_count = bind.execute(
        sa.text("SELECT count(*) FROM equipment WHERE legacy_status IS NULL")
    ).scalar_one()
    if null_legacy_count:
        raise RuntimeError(
            f"Migration 0006 downgrade aborted: {null_legacy_count} equipment row(s) have no "
            "legacy_status (created after this migration's upgrade under the 4-state-only "
            "application) and cannot have an 8-state value reconstructed for them without "
            "guessing. Back up and hand-resolve these rows before downgrading, or prefer a "
            "forward fix instead."
        )

    op.execute("ALTER TABLE equipment DROP CONSTRAINT IF EXISTS ck_equipment_status_four_state")
    op.execute("UPDATE equipment SET status = legacy_status")
    op.execute("ALTER TABLE equipment DROP COLUMN IF EXISTS legacy_status")
