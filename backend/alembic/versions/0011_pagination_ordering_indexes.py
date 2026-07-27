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
by tables that can grow large. A plain, non-concurrent `CREATE INDEX`
takes a `SHARE` lock on the table for the full build duration: ordinary
reads (`SELECT`) remain available throughout, but every write (`INSERT`/
`UPDATE`/`DELETE`, and any DDL) blocks until the build finishes -- on a
large table that can be minutes of blocked dispatch/receipt operations.
(This corrects an earlier draft of this docstring, which incorrectly
described the plain-`CREATE INDEX` lock as blocking reads too -- it does
not; only writes are blocked.) `CONCURRENTLY` avoids blocking either
reads or writes, at the cost of building the index in the background and
scanning the table twice, and does not require a maintenance window.

Trade-offs this deployment explicitly accepts: (1) `CREATE INDEX
CONCURRENTLY` cannot run inside a transaction block, so this migration
runs its work inside `op.get_context().autocommit_block()` -- each
statement commits on its own as soon as it completes, so this migration
is not atomic with whatever ran immediately before or after it in the
same `alembic upgrade` invocation (every other migration in this project
*is* one atomic transaction; this is a deliberate, documented exception).
(2) if a concurrent index build is interrupted (process killed,
connection lost, deadlock, or a genuine build failure such as a Postgres
crash mid-build), PostgreSQL leaves behind an INVALID index under the
target name.

That second point is exactly the failure mode a bare `CREATE INDEX
CONCURRENTLY IF NOT EXISTS` retry gets wrong: `IF NOT EXISTS` only checks
whether a relation with that name exists, not whether it is a complete,
usable index -- an interrupted run's INVALID index would satisfy
`IF NOT EXISTS` on the next attempt and be silently skipped forever,
letting Alembic record this migration as successful while the intended
index is still unusable. `_ensure_index_concurrently()` below closes that
gap: before deciding "already exists, nothing to do," it checks
`pg_index.indisvalid`/`indisready` and the index's actual definition via
`pg_indexes.indexdef`. Repository Owner's explicit direction: fail
closed, not auto-repair -- an INVALID index's root cause (interrupted
deployment, I/O problem, concurrent DDL) is something this migration
cannot determine, and silently dropping/rebuilding it could interact
badly with whatever caused the original interruption. On any unusable or
mismatched existing index, this migration raises `RuntimeError` and
refuses to continue, with an explicit operator remediation step in the
message -- matching this project's existing abort-closed convention (see
migration 0009's manifest/ambiguous-role validation).

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
IF NOT EXISTS (plus the validity/definition check above) makes that safe
regardless, but leaving the ORM model untouched avoids the drift question
entirely: 0001's behavior is identical before and after this migration
exists, and this migration is the single, sole source of truth for
whether these two indexes exist, on every path (fresh install, historical
upgrade, downgrade, re-upgrade). This mirrors how the GIN trigram indexes
(idx_equipment_bcm_trgm et al., migration 0004) are also migration-only
with no ORM declaration -- they are not expressible as a plain SQLAlchemy
`index=True` either, for the same underlying reason.

Purely additive: no existing table, column, constraint, or row is
touched, dropped, or altered. `equipment.deleted_at IS NULL` (the
soft-delete filter every equipment query already applies) is not part of
the index predicate -- a plain, non-partial composite index was
evidenced and is simpler to reason about; a partial-index refinement is
not ruled out for a future PR if evidence later justifies it, but is not
part of this change.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_pagination_ordering_indexes"
down_revision: Union[str, None] = "0010_inventory_import_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EQUIPMENT_INDEX = "ix_equipment_created_at_id"
TRANSACTIONS_INDEX = "ix_borrow_transactions_created_at_id"

_INDEX_SPECS = (
    (EQUIPMENT_INDEX, "equipment", "created_at DESC, id DESC"),
    (TRANSACTIONS_INDEX, "borrow_transactions", "created_at DESC, id DESC"),
)


def _expected_indexdef(index_name: str, table: str, columns_desc: str) -> str:
    # The exact canonical string PostgreSQL itself renders for this index
    # shape (confirmed against a live PostgreSQL 16 instance) -- used to
    # detect a same-named-but-differently-defined index, not just a
    # same-named-and-valid one.
    return f"CREATE INDEX {index_name} ON public.{table} USING btree ({columns_desc})"


def _ensure_index_concurrently(bind, *, index_name: str, table: str, columns_desc: str) -> None:
    """Fail-closed equivalent of `CREATE INDEX CONCURRENTLY IF NOT EXISTS`.

    A bare `IF NOT EXISTS` only checks whether a relation with this name
    exists -- not whether it is a complete, valid, correctly-defined
    index. This checks the PostgreSQL catalog directly (`pg_indexes`,
    `pg_index`) and refuses to treat an INVALID, NOT READY, or
    differently-defined existing index as "already done." See this
    module's docstring for the interrupted-build scenario this guards
    against, and why fail-closed (not auto-repair) was chosen.
    """
    expected_indexdef = _expected_indexdef(index_name, table, columns_desc)

    existing_indexdef = bind.execute(
        sa.text("SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' AND indexname = :name"),
        {"name": index_name},
    ).scalar_one_or_none()

    if existing_indexdef is not None:
        indisvalid, indisready = bind.execute(
            sa.text("SELECT indisvalid, indisready FROM pg_index WHERE indexrelid = to_regclass(:name)"),
            {"name": index_name},
        ).one()

        if not indisvalid or not indisready:
            raise RuntimeError(
                f"Migration 0011 aborted: index '{index_name}' already exists but is "
                f"not usable (indisvalid={indisvalid}, indisready={indisready}). This "
                "usually means a previous CREATE INDEX CONCURRENTLY was interrupted "
                "(process killed, connection lost, deadlock, or a genuine build "
                "failure). Refusing to silently continue and let this migration be "
                "recorded as successful while the intended index is still unusable. "
                f"Inspect the index, then run "
                f"'DROP INDEX CONCURRENTLY IF EXISTS {index_name};' and re-run this "
                "migration."
            )

        if existing_indexdef != expected_indexdef:
            raise RuntimeError(
                f"Migration 0011 aborted: index '{index_name}' already exists and is "
                "valid, but its definition does not match what this migration "
                f"expects.\n  Found:    {existing_indexdef}\n"
                f"  Expected: {expected_indexdef}\n"
                "This may be a different, unrelated index that happens to share this "
                "name. Refusing to silently continue -- inspect and resolve manually "
                "before re-running this migration."
            )

        # Valid, ready, and correctly defined: already done, nothing to do.
        return

    bind.execute(sa.text(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name} ON {table} ({columns_desc})"))


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            for index_name, table, columns_desc in _INDEX_SPECS:
                _ensure_index_concurrently(bind, index_name=index_name, table=table, columns_desc=columns_desc)
    else:
        # Migrations only ever run against PostgreSQL in this project (the
        # SQLite test/dev path never runs Alembic at all -- see 0002/0004's
        # identical branch). CONCURRENTLY and the catalog-based validity
        # check are both PostgreSQL-specific, so the fallback here is a
        # plain index -- never exercised in practice, kept only so this
        # migration does not hard-fail on an unsupported dialect.
        op.create_index(EQUIPMENT_INDEX, "equipment", ["created_at", "id"])
        op.create_index(TRANSACTIONS_INDEX, "borrow_transactions", ["created_at", "id"])


def downgrade() -> None:
    """Drops both ordering indexes. Purely a performance-characteristic
    change in reverse -- no data loss, no column/constraint change.
    Queries remain fully correct without these indexes (that was true
    before this migration existed); they simply revert to the slower
    sequential-scan-and-sort plan this migration's evidence document
    measured.

    No fail-closed validity check on this direction: dropping an index
    (valid, invalid, or not ready) is safe regardless -- PostgreSQL
    supports `DROP INDEX CONCURRENTLY` on an INVALID index specifically
    as the documented recovery path for an interrupted build, and there
    is no data-loss or silent-corruption risk symmetrical to upgrade's
    "recorded successful but actually unusable" failure mode."""
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {TRANSACTIONS_INDEX}")
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {EQUIPMENT_INDEX}")
    else:
        op.drop_index(TRANSACTIONS_INDEX, table_name="borrow_transactions")
        op.drop_index(EQUIPMENT_INDEX, table_name="equipment")
