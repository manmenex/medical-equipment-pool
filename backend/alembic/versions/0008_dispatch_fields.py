"""add dispatch_type, routine_round; relax borrower_name NOT NULL (Roadmap PR7b)

Revision ID: 0008_dispatch_fields
Revises: 0007_transaction_lifecycle
Create Date: 2026-07-20

Roadmap PR7b (docs/audits/04-consolidated-implementation-plan.md, Part D
PR7 entry; docs/ROADMAP.md "PR7 (7b slice)"): completes Roadmap PR7's
remaining scope left out of the 7a lifecycle-model slice
(knowledge/adr/ADR-005-transaction-model.md) --

  - dispatch_type   new, nullable, CHECK-restricted to the confirmed
                     two-value domain {'routine_round', 'on_demand'}
                     (docs/audits/04-consolidated-implementation-plan.md's
                     confirmed-requirements table).
  - routine_round    new, nullable, CHECK-restricted to the four confirmed
                     fixed times {'06:00', '11:00', '15:00', '21:00'}
                     (same table; repeated verbatim in docs/audits/
                     03-hospital-equipment-pool-workflow-audit.md's §12
                     acceptance criteria).
  - borrower_name    relaxed from NOT NULL to nullable -- the active
                     BorrowRequest contract (app.schemas.transaction) no
                     longer accepts or requires it, but every existing
                     value is preserved as read-only history, exactly
                     as-is.

`ward_id`-required-for-new-dispatches and `due_at`/`quantity` removal from
the write path are enforced at the application/schema/service layer only
(app.schemas.transaction.BorrowRequest, app.services.borrow_service) --
`ward_id` stays nullable at the database level (an existing NULL-`ward_id`
historical row is never auto-assigned a ward, per this plan's own explicit
instruction not to fabricate one), and `due_at`/`quantity` are unchanged
columns, simply no longer accepted as request input (their existing
values remain queryable/exportable -- e.g. app.services.report_service's
CSV/XLSX export reads both directly from the ORM row, unaffected by this
migration or the schema/API changes that accompany it).

Unlike migration 0007, this migration is purely additive: dispatch_type
and routine_round are brand-new columns with no prior value domain to
remap, so every existing row trivially satisfies every CHECK constraint
below (dispatch_type IS NULL AND routine_round IS NULL), and there is no
preflight-abort path on upgrade. Relaxing borrower_name's NOT NULL
constraint can never fail against existing data either (loosening a
constraint is always safe). This migration does NOT import
app.models.transaction or any other runtime application module
(PR5-H3R-MIG-style immutability, same rationale as migrations 0006/0007's
identical notes): the confirmed value domains are defined locally, frozen
at this revision.

Conditional consistency (CHECK
`ck_borrow_transactions_routine_round_consistency`): exactly one of --

  dispatch_type IS NULL           AND routine_round IS NULL  (historical,
                                                                pre-PR7b)
  dispatch_type = 'on_demand'     AND routine_round IS NULL  (on-demand)
  dispatch_type = 'routine_round' AND routine_round IS NOT NULL (routine)

-- is permitted; a `routine_round` value without a `'routine_round'`
`dispatch_type`, or a `'routine_round'` `dispatch_type` with no
`routine_round` value, is rejected at the database level as well as the
application layer (defense in depth, not either/or -- the application
layer is still the primary, user-facing gate; see
app.schemas.transaction.BorrowRequest's model_validator).

Schema convergence note: because `0001_initial.py` builds its schema from
*today's* `Base.metadata` (`Base.metadata.create_all()`, see
`docs/TECH_DEBT.md` TD-002), a database whose `0001` ran under this PR's
model change already has `dispatch_type`/`routine_round` columns and a
nullable `borrower_name` directly from `0001` -- but never the CHECK
constraints below (SQLAlchemy's non-native `Enum` type and a plain
nullable column carry no DB-level CHECK on their own; every CHECK in this
codebase is added explicitly via migration, exactly as
`ck_borrow_transactions_status_open_closed` was in migration 0007). This
migration's `ADD COLUMN IF NOT EXISTS` and unconditional `ALTER COLUMN
... DROP NOT NULL` are safe no-ops against that starting state, and its
`ADD CONSTRAINT` statements always run, so both a genuinely fresh
database and one upgraded from 0007 converge to the same final schema.

Downgrade: drops the two new columns and their three CHECK constraints --
fully reversible, no data loss, since neither column existed before this
migration. Restoring `borrower_name` to NOT NULL is explicit and
preflighted: it aborts, naming the affected row count, if any row has a
NULL `borrower_name` -- this can only happen for a dispatch created after
this migration's upgrade (the BorrowRequest contract no longer supplies
one), so restoring NOT NULL would either fail at the database level with
an unhelpful raw error or require fabricating a value; this migration
does neither and fails closed instead, exactly like migration 0007's
`legacy_status` downgrade guard. Prefer a forward fix over downgrading a
database that has taken real dispatches since this migration's upgrade.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_dispatch_fields"
down_revision: Union[str, None] = "0007_transaction_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Revision-local, frozen value domains. See the immutability note in this
# module's docstring -- deliberately NOT imported from app.models.transaction.
# ---------------------------------------------------------------------------

DISPATCH_TYPES: tuple[str, ...] = ("routine_round", "on_demand")
ROUTINE_ROUNDS: tuple[str, ...] = ("06:00", "11:00", "15:00", "21:00")


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        # Migrations only ever run against PostgreSQL in this project (see
        # 0002-0007's identical branch) -- the SQLite test/dev path builds
        # its schema via Base.metadata.create_all() directly from the ORM
        # models, which already reflect the new columns and the nullable
        # borrower_name. Nothing to do for any other dialect.
        return

    op.execute("ALTER TABLE borrow_transactions ADD COLUMN IF NOT EXISTS dispatch_type VARCHAR(20)")
    op.execute("ALTER TABLE borrow_transactions ADD COLUMN IF NOT EXISTS routine_round VARCHAR(5)")
    op.execute("ALTER TABLE borrow_transactions ALTER COLUMN borrower_name DROP NOT NULL")

    dispatch_type_list = ", ".join(f"'{value}'" for value in DISPATCH_TYPES)
    op.execute(
        "ALTER TABLE borrow_transactions ADD CONSTRAINT ck_borrow_transactions_dispatch_type "
        f"CHECK (dispatch_type IS NULL OR dispatch_type IN ({dispatch_type_list}))"
    )

    routine_round_list = ", ".join(f"'{value}'" for value in ROUTINE_ROUNDS)
    op.execute(
        "ALTER TABLE borrow_transactions ADD CONSTRAINT ck_borrow_transactions_routine_round "
        f"CHECK (routine_round IS NULL OR routine_round IN ({routine_round_list}))"
    )

    op.execute(
        "ALTER TABLE borrow_transactions ADD CONSTRAINT ck_borrow_transactions_routine_round_consistency "
        "CHECK ("
        "(dispatch_type IS NULL AND routine_round IS NULL) "
        "OR (dispatch_type = 'on_demand' AND routine_round IS NULL) "
        "OR (dispatch_type = 'routine_round' AND routine_round IS NOT NULL)"
        ")"
    )


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    null_borrower_name_count = bind.execute(
        sa.text("SELECT count(*) FROM borrow_transactions WHERE borrower_name IS NULL")
    ).scalar_one()
    if null_borrower_name_count:
        raise RuntimeError(
            f"Migration 0008 downgrade aborted: {null_borrower_name_count} borrow_transactions row(s) "
            "have a NULL borrower_name (created after this migration's upgrade, under a contract that "
            "no longer requires or accepts one) and cannot have NOT NULL restored without fabricating "
            "a value. Back up and hand-resolve these rows before downgrading, or prefer a forward fix "
            "instead."
        )

    op.execute(
        "ALTER TABLE borrow_transactions DROP CONSTRAINT IF EXISTS "
        "ck_borrow_transactions_routine_round_consistency"
    )
    op.execute("ALTER TABLE borrow_transactions DROP CONSTRAINT IF EXISTS ck_borrow_transactions_routine_round")
    op.execute("ALTER TABLE borrow_transactions DROP CONSTRAINT IF EXISTS ck_borrow_transactions_dispatch_type")
    op.execute("ALTER TABLE borrow_transactions ALTER COLUMN borrower_name SET NOT NULL")
    op.execute("ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS routine_round")
    op.execute("ALTER TABLE borrow_transactions DROP COLUMN IF EXISTS dispatch_type")
