"""collapse the three-value borrow_transactions status to the confirmed OPEN/CLOSED model

Revision ID: 0007_transaction_lifecycle
Revises: 0006_equipment_state_model
Create Date: 2026-07-20

Roadmap PR7 (docs/audits/04-consolidated-implementation-plan.md, Part D;
knowledge/adr/ADR-005-transaction-model.md): replaces the legacy
three-value `borrow_transactions.status` domain (borrowed, returned,
overdue) with the confirmed two-state transaction lifecycle from
`HOSPITAL_DOMAIN_MODEL.md`:

  - open
  - closed

Every remapped row's original pre-migration value is preserved verbatim in
a new nullable `legacy_status` column -- historical/rollback metadata
only, never read by any workflow or eligibility check (mirrors
`app.models.equipment.Equipment.legacy_status`, Roadmap PR6 precedent).

Legacy-to-target mapping (exhaustive -- see LEGACY_STATUS_MAP below):

  borrowed  -> open     (still awaiting receipt)
  returned  -> closed   (already received)
  overdue   -> open     (still awaiting receipt; HOSPITAL_DOMAIN_MODEL.md:
                          "no active due-date or overdue state in the
                          confirmed workflow" -- overdue was never a third
                          lifecycle state, only a due_at-driven notification
                          flag written by app.worker.scheduler, which this
                          same Roadmap PR7 change stops writing)

This migration does NOT import app.models.transaction, app.core.exceptions,
or any other runtime application module (PR5-H3R-MIG-style immutability,
same rationale as migration 0006's identical note): the legacy-to-target
mapping and the two-state target set are defined locally, frozen at this
revision.

Unlike migration 0006's equipment.status (which used SQLAlchemy's `Enum`
type without `values_callable` before Roadmap PR6 fixed it), the pre-PR7
`borrow_transactions.status` column was always a plain `String(20)` column
-- application code only ever wrote the literal values `"borrowed"`,
`"returned"`, `"overdue"`. There is no equivalent uppercase-name-vs-value
ambiguity to defend against here.

Preflight (upgrade): every distinct existing `status` value is checked
against LEGACY_STATUS_MAP's keys, with one exception -- a value that is
already one of the two target states is left untouched and does not
receive a `legacy_status` (this makes the migration safe to run against a
database whose `borrow_transactions` table was created fresh via
`Base.metadata.create_all()` at 0001, which already reflects today's
OPEN/CLOSED default and already has a `legacy_status` column -- see
migration 0006's docstring for why 0001 behaves this way). Any OTHER
distinct value aborts the migration before any row is written, naming
every unexpected value and its row count -- never a guess, never a
partial remap.

Verification (upgrade): row count unchanged; no row is left with a NULL
`status`; every `status` value belongs to the two-state target set; every
row whose `status` changed carries its exact original value in
`legacy_status`.

The partial unique index enforcing "at most one OPEN transaction per
equipment" (`idx_tx_one_active_borrow`, the real guard against a
double-dispatch race -- see `app.models.transaction.BorrowTransaction`)
is dropped and recreated with the new `status = 'open'` predicate,
unconditionally, so it is correct regardless of whether the table was
freshly created (already `open`-predicated by the current ORM model) or
remapped by this migration.

Constraint timing: `ck_borrow_transactions_status_open_closed` (CHECK) is
added only after the verification above passes, so a database that fails
preflight or verification is left with no new constraint and no
partially-remapped data (the whole migration runs inside Alembic's
transactional DDL).

Downgrade: aborts cleanly, with no partial restoration, if any row has a
NULL `legacy_status` -- such a row was created after this migration's
upgrade (the OPEN/CLOSED-only application no longer writes a legacy
value), so there is no original value to reconstruct and guessing one
would corrupt data (note: a row remapped from `overdue` restores to
`borrowed`, not `overdue` -- `overdue` was never a real status write path
after this migration, only a legacy value being reversed). If every row
has a `legacy_status`, the CHECK constraint and the new partial index are
dropped, `status` is restored from `legacy_status` for every row, the old
`status = 'borrowed'`-predicated partial index is recreated, and the
`legacy_status` column itself is then dropped -- symmetric with 0006's
downgrade convention for a column this migration purely added. Prefer a
forward fix over downgrading a database that has taken real writes since
this migration's upgrade.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_transaction_lifecycle"
down_revision: Union[str, None] = "0006_equipment_state_model"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Revision-local, frozen mapping. See the immutability note in this module's
# docstring -- deliberately NOT imported from app.models.transaction.
# ---------------------------------------------------------------------------

LEGACY_STATUS_MAP: dict[str, str] = {
    "borrowed": "open",
    "returned": "closed",
    "overdue": "open",
}

TARGET_STATUSES: tuple[str, ...] = ("open", "closed")


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        # Migrations only ever run against PostgreSQL in this project (see
        # 0002-0006's identical branch) -- the SQLite test/dev path builds
        # its schema via Base.metadata.create_all() directly from the ORM
        # models, which already reflect the OPEN/CLOSED default and the
        # legacy_status column. Nothing to do for any other dialect.
        return

    op.execute("ALTER TABLE borrow_transactions ADD COLUMN IF NOT EXISTS legacy_status VARCHAR(20)")

    before_count = bind.execute(sa.text("SELECT count(*) FROM borrow_transactions")).scalar_one()

    rows = bind.execute(
        sa.text("SELECT status, count(*) FROM borrow_transactions GROUP BY status")
    ).fetchall()
    distinct_statuses = {row[0] for row in rows}
    counts_by_status = {row[0]: row[1] for row in rows}

    target_set = set(TARGET_STATUSES)
    unexpected = distinct_statuses - set(LEGACY_STATUS_MAP.keys()) - target_set
    if unexpected:
        details = "\n".join(
            f"  {value!r}: {counts_by_status[value]} row(s)" for value in sorted(unexpected)
        )
        raise RuntimeError(
            "Migration 0007 aborted: the following unexpected borrow_transactions.status values "
            "were found and have no approved mapping to the OPEN/CLOSED model. Resolve these by "
            "hand (correct the data or extend the approved mapping in a new migration) before "
            "re-running this migration -- nothing has been remapped:\n" + details
        )

    # Deterministic, one UPDATE per legacy source value actually present.
    # Values already in the target set (a fresh database created via 0001's
    # create_all(), see module docstring) are left untouched -- no
    # legacy_status is invented for them.
    for legacy_value, target_value in LEGACY_STATUS_MAP.items():
        if legacy_value not in counts_by_status:
            continue
        bind.execute(
            sa.text(
                "UPDATE borrow_transactions SET legacy_status = status, status = :target "
                "WHERE status = :legacy"
            ),
            {"target": target_value, "legacy": legacy_value},
        )

    after_count = bind.execute(sa.text("SELECT count(*) FROM borrow_transactions")).scalar_one()
    if after_count != before_count:
        raise RuntimeError(
            f"Migration 0007 aborted: row count changed during remap ({before_count} -> {after_count}); "
            "no constraint has been added."
        )

    null_status_count = bind.execute(
        sa.text("SELECT count(*) FROM borrow_transactions WHERE status IS NULL")
    ).scalar_one()
    if null_status_count:
        raise RuntimeError(
            f"Migration 0007 aborted: {null_status_count} row(s) have a NULL status after remap; "
            "no constraint has been added."
        )

    non_target_count = bind.execute(
        sa.text("SELECT count(*) FROM borrow_transactions WHERE status NOT IN ('open', 'closed')")
    ).scalar_one()
    if non_target_count:
        raise RuntimeError(
            f"Migration 0007 aborted: {non_target_count} row(s) have a status outside the "
            "OPEN/CLOSED target set after remap; no constraint has been added."
        )

    for legacy_value, target_value in LEGACY_STATUS_MAP.items():
        expected = counts_by_status.get(legacy_value, 0)
        if expected == 0:
            continue
        actual = bind.execute(
            sa.text(
                "SELECT count(*) FROM borrow_transactions WHERE status = :target AND legacy_status = :legacy"
            ),
            {"target": target_value, "legacy": legacy_value},
        ).scalar_one()
        if actual != expected:
            raise RuntimeError(
                f"Migration 0007 aborted: expected {expected} row(s) remapped from {legacy_value!r} to "
                f"{target_value!r} with legacy_status preserved, found {actual}; no constraint has been added."
            )

    # Recreate the "at most one OPEN transaction per equipment" guard with
    # the new predicate. Unconditional drop+create so it ends up correct
    # regardless of the table's starting state (freshly created via 0001,
    # already open-predicated -- or an existing database just remapped
    # above).
    op.execute("DROP INDEX IF EXISTS idx_tx_one_active_borrow")
    op.execute(
        "CREATE UNIQUE INDEX idx_tx_one_active_borrow ON borrow_transactions (equipment_id) "
        "WHERE status = 'open'"
    )

    op.execute(
        "ALTER TABLE borrow_transactions ADD CONSTRAINT ck_borrow_transactions_status_open_closed "
        "CHECK (status IN ('open', 'closed'))"
    )


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    null_legacy_count = bind.execute(
        sa.text("SELECT count(*) FROM borrow_transactions WHERE legacy_status IS NULL")
    ).scalar_one()
    if null_legacy_count:
        raise RuntimeError(
            f"Migration 0007 downgrade aborted: {null_legacy_count} borrow_transactions row(s) have "
            "no legacy_status (created after this migration's upgrade under the OPEN/CLOSED-only "
            "application) and cannot have a pre-PR7 status reconstructed for them without guessing. "
            "Back up and hand-resolve these rows before downgrading, or prefer a forward fix instead."
        )

    op.execute("ALTER TABLE borrow_transactions DROP CONSTRAINT IF EXISTS ck_borrow_transactions_status_open_closed")
    op.execute("DROP INDEX IF EXISTS idx_tx_one_active_borrow")
    op.execute("UPDATE borrow_transactions SET status = legacy_status")
    op.execute(
        "CREATE UNIQUE INDEX idx_tx_one_active_borrow ON borrow_transactions (equipment_id) "
        "WHERE status = 'borrowed'"
    )
    op.execute("ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS legacy_status")
