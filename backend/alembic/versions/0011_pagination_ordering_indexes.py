"""add composite (created_at DESC, id DESC) ordering indexes for cursor pagination (Roadmap PR14B)

Revision ID: 0011_pagination_ordering_indexes
Revises: 0010_inventory_import_columns
Create Date: 2026-07-27

Roadmap PR14B (Pagination Performance) -- the second slice of Roadmap
PR14, gated on EXPLAIN ANALYZE evidence before any index/pagination
change was designed (per Repository Owner instruction). Strictly
index-only: no API behavior change, no pagination-logic change, no
`COUNT(*)` change, no endpoint contract change.

Evidence (docs/audits/06-pr14b-pagination-index-evidence.md has the full
EXPLAIN (ANALYZE, BUFFERS) output this migration is based on): both
`app.crud.equipment.search()` and `app.crud.transaction.search()` order
their cursor-paginated result set by `ORDER BY created_at DESC, id DESC`
against `equipment`/`borrow_transactions`, and `TimestampMixin.created_at`
(app/models/mixins.py) carries no index. Against a synthetic dataset
seeded to the scale the original Backend Audit 5.2 finding was framed
against (200,000 equipment rows, 1,000,000 transaction rows, realistic
non-clustered timestamps spread across ~2 years), the first-page query
(no cursor -- by far the dominant real access pattern: initial page load,
dashboard, refresh) cost ~55ms on equipment and ~134-205ms on
transactions via a full parallel sequential scan + top-N sort, on every
single call. With this index, the same queries drop to ~0.05-0.3ms via a
plain Index Scan (no Sort node) -- roughly a 500-2000x improvement.
Shallow-to-moderate cursor depths (measured at 250/2,500/25,000 rows
past the first page) also improve or stay comparable.

Known, accepted limitation (index-only scope; fixing this would be a
pagination-logic redesign, explicitly out of scope for PR14B): the
cursor WHERE clause is `created_at < :cursor OR (created_at = :cursor AND
id < :cursor_id)`, a disjunctive (OR-of-AND) condition. PostgreSQL cannot
translate this into a single sargable index-range boundary against a
plain two-column btree index -- it can only push `created_at <=
:cursor` in as an Index Cond and must apply the rest as a Filter, walking
every index entry from the start of the matching `created_at` range until
it finds 26 that pass. Measured at very deep cursor offsets (250,000 and
500,000 rows past the first page, out of 1,000,000), this Filter walk
made the indexed query *slower* than the pre-index sequential scan
(2.6s vs ~0.15s at 500,000 rows deep) -- PostgreSQL's cost estimator
chose the index path anyway (it does not know in advance how many rows
the Filter will discard). At this system's confirmed business scale (an
Equipment Pool fleet -- "low hundreds of devices, thousands of
transactions per year", not a hospital-wide asset register), reaching a
cursor 250,000+ rows deep is not a realistically reachable UI access
pattern (tens of thousands of "next page" clicks), so this is accepted
as a known, documented, currently-unreachable-in-practice trade-off
rather than a blocker -- see the evidence document for the full
depth-vs-latency table and the crossover point (~75,000-100,000 rows).

Deployment safety -- `CREATE INDEX CONCURRENTLY` (not plain `CREATE
INDEX`): `equipment` and `borrow_transactions` are actively
read/written during normal hospital-equipment-pool operation (dispatch,
receipt, PM/CAL scheduling), and this migration is specifically motivated
by tables that can grow large -- exactly the case where a plain `CREATE
INDEX`'s ACCESS EXCLUSIVE lock (blocking all reads and writes on the
table for the full build duration) is least acceptable. `CONCURRENTLY`
avoids that at the cost of building the index in the background without
blocking concurrent DML, and does not require a maintenance window.
Trade-offs this deployment explicitly accepts: (1) `CREATE INDEX
CONCURRENTLY` cannot run inside a transaction block, so this migration
runs the two `CREATE INDEX CONCURRENTLY IF NOT EXISTS` statements inside
`op.get_context().autocommit_block()` -- each statement commits on its
own as soon as it completes, so this migration is not atomic with
whatever ran immediately before or after it in the same `alembic upgrade`
invocation (every other migration in this project *is* one atomic
transaction; this is a deliberate, documented exception). (2) if a
concurrent index build is interrupted (process killed, connection lost),
PostgreSQL can leave behind an INVALID index that must be dropped and
recreated -- this migration's `IF NOT EXISTS` guard does not detect or
repair that state automatically; operators should check
`pg_index.indisvalid` after a failed/interrupted run of this migration
before assuming success.

IF NOT EXISTS everywhere, dialect-gated postgresql/else (same pattern as
0002_audit_request_ids.py and 0004_equipment_item_no_bcm_code.py, see
their docstrings): 0001_initial's create_all() reflects whatever the ORM
models look like *at the time it runs*, not a frozen snapshot -- but
unlike 0004, this migration deliberately does NOT add anything to the
SQLAlchemy models (app/models/equipment.py, app/models/transaction.py).
Declaring `index=True` on `created_at` would mean a fresh database's
0001 already creates this index (since 0001 dynamically reflects current
ORM state, see TD-002 / docs/TECH_DEBT.md), and this dedicated migration
would then be racing 0001's own index for the same name on that path --
IF NOT EXISTS makes that safe regardless, but leaving the ORM model
untouched avoids the drift question entirely: 0001's behavior is
identical before and after this migration exists, and this migration is
the single, sole source of truth for whether these two indexes exist, on
every path (fresh install, historical upgrade, downgrade, re-upgrade).
This mirrors how the GIN trigram indexes (idx_equipment_bcm_trgm et al.,
migration 0004) are also migration-only with no ORM declaration -- they
are not expressible as a plain SQLAlchemy `index=True` either, for the
same underlying reason.

Purely additive: no existing table, column, constraint, or row is
touched, dropped, or altered. `equipment.deleted_at IS NULL` (the
soft-delete filter every equipment query already applies) is not part of
the index predicate -- a plain, non-partial composite index was
evidenced and is simpler to reason about; a partial-index refinement is
not ruled out for a future PR if evidence later justifies it, but is not
part of this change.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0011_pagination_ordering_indexes"
down_revision: Union[str, None] = "0010_inventory_import_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EQUIPMENT_INDEX = "ix_equipment_created_at_id"
TRANSACTIONS_INDEX = "ix_borrow_transactions_created_at_id"


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {EQUIPMENT_INDEX} "
                "ON equipment (created_at DESC, id DESC)"
            )
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {TRANSACTIONS_INDEX} "
                "ON borrow_transactions (created_at DESC, id DESC)"
            )
    else:
        # Migrations only ever run against PostgreSQL in this project (the
        # SQLite test/dev path never runs Alembic at all -- see 0002/0004's
        # identical branch). CONCURRENTLY is PostgreSQL-specific, so the
        # fallback here is a plain index -- never exercised in practice,
        # kept only so this migration does not hard-fail on an unsupported
        # dialect.
        op.create_index(EQUIPMENT_INDEX, "equipment", ["created_at", "id"])
        op.create_index(TRANSACTIONS_INDEX, "borrow_transactions", ["created_at", "id"])


def downgrade() -> None:
    """Drops both ordering indexes. Purely a performance-characteristic
    change in reverse -- no data loss, no column/constraint change.
    Queries remain fully correct without these indexes (that was true
    before this migration existed); they simply revert to the slower
    sequential-scan-and-sort plan this migration's evidence document
    measured."""
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {TRANSACTIONS_INDEX}")
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {EQUIPMENT_INDEX}")
    else:
        op.drop_index(TRANSACTIONS_INDEX, table_name="borrow_transactions")
        op.drop_index(EQUIPMENT_INDEX, table_name="equipment")
