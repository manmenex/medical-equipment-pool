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

Preflight (upgrade), in order, before any row is written:

1. Every distinct existing `status` value is checked against
   LEGACY_STATUS_MAP's keys, with one exception -- a value that is
   already one of the two target states is left untouched by the
   legacy-remap step below (it is not a member of `LEGACY_STATUS_MAP`,
   so there is no legacy-to-target rewrite to apply to it), and it does
   NOT receive a `legacy_status` at that point (this makes the migration
   safe to run against a database whose `borrow_transactions` table was
   created fresh via `Base.metadata.create_all()` at 0001, which already
   reflects today's OPEN/CLOSED default -- see migration 0006's docstring
   for why 0001 behaves this way). It is *not* left with a permanently
   NULL `legacy_status`, though: see "Target-state compatibility policy"
   below for the separate step, later in `upgrade()`, that gives every
   such row a same-value compatibility marker. Any OTHER distinct value
   aborts the migration, naming every unexpected value and its row
   count -- never a guess, never a partial remap.
2. Future-OPEN collision check: every status value that will read as
   `open` after this migration -- `borrowed` and `overdue` (both remap to
   `open`) *and* `open` itself (a row already in the target domain, left
   untouched by the remap) -- is FUTURE_OPEN_STATUSES. The pre-migration
   partial unique index (`idx_tx_one_active_borrow`, predicate `status =
   'borrowed'`) only ever guarded uniqueness among `borrowed` rows -- it
   never constrained `overdue` or a raw `open` row at all, so a database
   could legally hold any combination of `borrowed`/`overdue`/`open` rows
   for the same `equipment_id` simultaneously pre-migration. Collapsing
   all of them to `open` would violate the new `status = 'open'` unique
   index this migration creates, and would otherwise surface as a raw,
   unhelpful `UniqueViolation` from the `CREATE UNIQUE INDEX` statement
   after data has already been rewritten. This migration instead queries
   for any `equipment_id` with more than one row in FUTURE_OPEN_STATUSES
   *before* touching any row, and aborts with the exact offending
   equipment IDs if any are found -- see
   `_equipment_ids_with_multiple_future_open_rows()` below (Codex PR7a
   review round 1, "Future-OPEN collision preflight"; widened in review
   round 2, MAJOR 1, to also count pre-existing `open` rows, which the
   round 1 version missed).

Verification (upgrade): row count unchanged; no row is left with a NULL
`status`; every `status` value belongs to the two-state target set; every
row whose `status` changed carries its exact original value in
`legacy_status`.

Schema convergence (upgrade): the pre-PR7 ORM model declared `status` as
a plain `String(20)` column, so a database that ran migration `0001`
before this PR's app-code change got a physical `VARCHAR(20)` column.
Because `0001_initial.py` builds its schema from *today's* `Base.metadata`
(`Base.metadata.create_all()`, see `docs/TECH_DEBT.md` TD-002), a
database whose `0001` ran *after* this PR's model change already has
`VARCHAR(10)` (today's `TransactionStatusType(length=10)`). Without an
explicit `ALTER COLUMN ... TYPE`, those two databases would permanently
diverge in physical column width even though both are at migration head.
This migration narrows `status` to `VARCHAR(10)` unconditionally (a safe
no-op if already that width) once the remap/verification above has
proven every value is `open` or `closed` (4/6 characters, well within 10).

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

Target-state compatibility policy (Codex PR7a review round 2, MAJOR 2):
a row already `open` or `closed` *before* this migration ran (see
preflight step 1 above -- a table created fresh via `Base.metadata.
create_all()` at 0001, or any row otherwise already in the target
domain) never had a real pre-PR7 status: `LEGACY_STATUS_MAP` has no
entry for it, so the remap loop never touches it. Round 1 of this
migration left such a row's `legacy_status` NULL, which meant an upgrade
could succeed while the documented downgrade could never run for that
database -- the NULL-`legacy_status` abort below would always fire, even
immediately after upgrade with zero genuinely new writes. Fixed: after
the remap loop runs, every row whose `legacy_status` is still NULL (by
construction, exactly the rows that started already `open`/`closed`) has
`legacy_status` set to its own current `status` value -- a canonical
downgrade-compatibility marker, not a claim about pre-PR7 history that
does not exist. This is what distinguishes the two cases on read:
`legacy_status IN ('borrowed', 'returned', 'overdue')` is always a
genuine preserved legacy value (the row's exact original status);
`legacy_status IN ('open', 'closed')` is always a synthetic compatibility
marker meaning "this row had no real legacy value; it was already in the
target domain when this migration ran" -- `LEGACY_STATUS_MAP`'s remap
never produces `legacy_status = 'open'` or `'closed'` for a row it
actually remapped, so the two populations can never be confused. A row
created *after* this migration's upgrade (the OPEN/CLOSED-only
application never writes `legacy_status` at all) still has a NULL
`legacy_status` and is unaffected by this policy -- see Downgrade below.

Downgrade: aborts cleanly, with no partial restoration, if any row has a
NULL `legacy_status` -- given the compatibility policy above, this can
now only happen for a row created after this migration's upgrade ran
(genuinely unreconstructable -- there is no original value to guess, and
guessing one would corrupt data; fail closed rather than fabricate
history). If every row has a `legacy_status`, the CHECK constraint and
the new partial index are dropped, `status` is restored verbatim from
`legacy_status` for every row: a row originally `overdue` is restored to
the literal value `overdue`, not `borrowed` (this migration's remap
collapses both `borrowed` and `overdue` to `open`, but downgrade reverses
each row to its own exact original value, not to a canonical
"OPEN-equivalent" representative -- Codex PR7a review round 1, "Migration
rollback documentation"); a row that started already `open`/`closed`
restores to that same value via its compatibility marker (a no-op that
correctly reproduces its true pre-migration state, since it never
changed). `status` is then widened back to `VARCHAR(20)`, matching the
pre-PR7 `String(20)` column the ORM model declared before this migration
existed. Finally the old `status = 'borrowed'`-predicated partial index
is recreated and the `legacy_status` column itself is dropped --
symmetric with 0006's downgrade convention for a column this migration
purely added. Prefer a forward fix over downgrading a database that has
taken real writes since this migration's upgrade.
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

# Every current status value that will read as "open" once this migration
# completes: 'borrowed' and 'overdue' remap to 'open' (LEGACY_STATUS_MAP),
# and 'open' itself is left untouched because it is already the target
# value. See "Future-OPEN collision preflight" in this module's docstring.
# (Codex PR7a review round 2, MAJOR 1: round 1's version of this tuple
# omitted 'open', so a database holding e.g. one legacy 'borrowed' row and
# one already-'open' row for the same equipment was not caught here.)
FUTURE_OPEN_STATUSES: tuple[str, ...] = ("borrowed", "overdue", "open")


def _equipment_ids_with_multiple_future_open_rows(bind) -> list[str]:
    # FUTURE_OPEN_STATUSES is a small, frozen, revision-local tuple (not
    # user input) -- inlined as a literal IN list, matching this module's
    # existing style (e.g. the "NOT IN ('open', 'closed')" check below),
    # rather than parameterized as an array bind.
    in_list = ", ".join(f"'{value}'" for value in FUTURE_OPEN_STATUSES)
    rows = bind.execute(
        sa.text(
            f"SELECT equipment_id FROM borrow_transactions "
            f"WHERE status IN ({in_list}) "
            f"GROUP BY equipment_id HAVING count(*) > 1 "
            f"ORDER BY equipment_id"
        )
    ).fetchall()
    return [str(row[0]) for row in rows]


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

    # Future-OPEN collision preflight (Codex PR7a review round 1; widened in
    # review round 2, MAJOR 1): every status value that will read as 'open'
    # after this migration -- 'borrowed', 'overdue', AND a pre-existing
    # 'open' row itself -- is FUTURE_OPEN_STATUSES. The pre-migration unique
    # index only ever guarded 'borrowed' rows -- an 'overdue' or already-
    # 'open' row for the same equipment was never blocked. Collapsing more
    # than one of them to 'open' would collide on the new unique index.
    # Detect and abort with the exact affected equipment IDs before any row
    # is modified.
    colliding_equipment_ids = _equipment_ids_with_multiple_future_open_rows(bind)
    if colliding_equipment_ids:
        raise RuntimeError(
            "Migration 0007 aborted: the following equipment_id(s) have more than one "
            f"future-OPEN ({', '.join(FUTURE_OPEN_STATUSES)}) borrow_transactions row. "
            "Collapsing all of them to 'open' would violate the 'at most one OPEN transaction "
            "per equipment' invariant. Resolve these by hand (close the stale row(s) or correct the "
            "data) before re-running this migration -- nothing has been remapped:\n"
            + "\n".join(f"  {equipment_id}" for equipment_id in colliding_equipment_ids)
        )

    # Deterministic, one UPDATE per legacy source value actually present.
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

    # Target-state compatibility marker (Codex PR7a review round 2, MAJOR 2
    # -- see this module's docstring, "Target-state compatibility policy").
    # A row already 'open'/'closed' before this migration ran has no entry
    # in LEGACY_STATUS_MAP, so the loop above never touches it and its
    # legacy_status is still NULL at this point. Set it to the row's own
    # current status -- never a value from LEGACY_STATUS_MAP's keys, which
    # is what makes a compatibility marker distinguishable on read from a
    # genuine preserved legacy value.
    bind.execute(sa.text("UPDATE borrow_transactions SET legacy_status = status WHERE legacy_status IS NULL"))

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

    # Schema convergence (Codex PR7a review round 1): narrow status to
    # VARCHAR(10) so a database whose 0001 ran under the pre-PR7
    # String(20) model converges to the same physical width as a database
    # whose 0001 ran under today's TransactionStatusType(length=10) --
    # see this module's docstring, "Schema convergence (upgrade)". Every
    # value has just been proven to be 'open' or 'closed' (4/6 chars), so
    # this is safe; a no-op if the column is already VARCHAR(10).
    op.execute("ALTER TABLE borrow_transactions ALTER COLUMN status TYPE VARCHAR(10)")

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
    # Restore the previous physical width. Legacy values ("borrowed",
    # "returned", "overdue") already fit in VARCHAR(10) too, so this isn't
    # required for the data about to be restored -- it exists to converge
    # the schema back to what the pre-PR7 String(20) ORM model declared
    # (see this module's docstring, "Downgrade").
    op.execute("ALTER TABLE borrow_transactions ALTER COLUMN status TYPE VARCHAR(20)")
    op.execute("UPDATE borrow_transactions SET status = legacy_status")
    op.execute(
        "CREATE UNIQUE INDEX idx_tx_one_active_borrow ON borrow_transactions (equipment_id) "
        "WHERE status = 'borrowed'"
    )
    op.execute("ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS legacy_status")
