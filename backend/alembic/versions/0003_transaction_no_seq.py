"""add transaction_no_seq global sequence

Revision ID: 0003_transaction_no_seq
Revises: 0002_audit_request_ids
Create Date: 2026-07-17

Roadmap PR4 (docs/kickoffs/PR4-architecture-kickoff.md, squash commit
91b23b62d864edadb430d1f4335c6b77e59222f0): replaces the racy
COUNT(*)...LIKE transaction-number generator with a single global,
concurrency-safe PostgreSQL SEQUENCE (transaction_no_seq).

This migration is purely additive: it creates one new database object
(the sequence) and touches no existing table, column, or row.

Safe-cutover seeding (the actual point of this migration, per the
kickoff's "Cutover and initialization requirement"): this project is not
a fresh-database-only deployment. By the time this migration runs, the
legacy generator may already have written transaction_no values for
*any* date, including today's (a same-day cutover, e.g. deploying
mid-way through an active business day between routine rounds). Creating
the sequence at PostgreSQL's unconditional default start value of 1
would make its first nextval() reproduce an already-existing suffix,
violating the UNIQUE constraint on borrow_transactions.transaction_no
and failing the very next dispatch.

So before creating the sequence, this migration scans ALL existing
transaction_no values (every date, not just historical dates before
today), parses each one against the exact shape
`TX-{8-digit date}-{one or more numeric digits}` (the numeric suffix is
variable-length and unbounded — the legacy generator's `:04d` formatting
is a *minimum* width via zero-padding, not a maximum, so a valid
historical suffix may already be 4, 5, 8, 9, or more digits), safely
skips any value that does not match that shape (e.g. this project's own
test fixture value "TX-TEST-0001" — never treated as an error and never
treated as 0, so it can't corrupt or suppress a real maximum), and seeds
the sequence strictly above the highest successfully-parsed suffix. A
genuinely empty/fresh database naturally computes a maximum of 0 and the
sequence starts at 1 as a *result* of that computation, never as a
hardcoded default.

Owner Decision 4 (deployment/cutover): this migration alone does not
guarantee a safe cutover — it must be run only after new
`POST /api/v1/borrow` dispatch creation has been paused and any legacy
COUNT+LIKE writer confirmed no longer active, per the documented
operational sequence in this PR's description. Running this migration
concurrently with live legacy-generator traffic can still race between
"scan computed the max" and "a legacy write lands" — see the kickoff's
"Concurrency expectations for cutover itself."

Disaster recovery: if this sequence object is ever lost (dropped, or a
restore from a backup predating it) and must be recreated, downgrading
and re-upgrading this same revision reruns the identical seeding logic
below, recomputed against transaction_no rows as they exist at that
later moment — there is no separate disaster-recovery-only code path.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_transaction_no_seq"
down_revision: Union[str, None] = "0002_audit_request_ids"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Exact shape a legacy transaction_no must match to be considered a valid
# source of a historical numeric suffix: TX- + 8 digit date + - + 1 or
# more digits, and nothing else (anchored both ends). Any other value
# (malformed, legacy-format, or otherwise non-conforming, e.g. this
# project's own test fixture "TX-TEST-0001") is skipped.
_VALID_TRANSACTION_NO_PATTERN = r"^TX-[0-9]{8}-[0-9]+$"


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        # Migrations only ever run against PostgreSQL in this project —
        # the SQLite test/dev path never runs Alembic at all (schema is
        # built via Base.metadata.create_all(), see
        # backend/tests/conftest.py), and generate_transaction_no()'s
        # SQLite fallback does not use transaction_no_seq. Nothing to do
        # for any other dialect (same rationale as 0002's identical
        # branch).
        return

    max_suffix = bind.execute(
        sa.text(
            "SELECT COALESCE("
            "MAX(CAST(substring(transaction_no from '^TX-[0-9]{8}-([0-9]+)$') AS BIGINT)), "
            "0"
            ") FROM borrow_transactions WHERE transaction_no ~ :pattern"
        ),
        {"pattern": _VALID_TRANSACTION_NO_PATTERN},
    ).scalar_one()

    start_value = max_suffix + 1

    # IF NOT EXISTS makes this idempotent against a partially-applied
    # prior attempt at this same revision. START WITH on a genuinely new
    # sequence means the first nextval() returns exactly start_value (a
    # freshly created sequence has not yet been "called").
    op.execute(f"CREATE SEQUENCE IF NOT EXISTS transaction_no_seq START WITH {start_value}")


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP SEQUENCE IF EXISTS transaction_no_seq")
