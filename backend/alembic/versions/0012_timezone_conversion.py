"""convert five naive timestamp columns to timestamptz (Roadmap PR15B, Migration A)

Revision ID: 0012_timezone_conversion
Revises: 0011_pagination_ordering_indexes
Create Date: 2026-07-28

Roadmap PR15B (Schema Hygiene), Migration A of three
(docs/design/PR15B_SCHEMA_HYGIENE_PLAN.md, GitHub PR #52, architecture-
approved) -- see §3/§8.2/§8.7 for the full rationale this docstring
summarizes.

**What this converts, and why exactly these five.** `audit_logs.created_at`,
`notifications.created_at`, `equipment_status_history.changed_at`,
`borrow_transactions.borrowed_at`, and `.returned_at` are all naive
`timestamp without time zone` columns whose entire write history is
`datetime.utcnow()` (confirmed by tracing every write path, §3.2/§3.3) --
a wall-clock value with no stored timezone semantics, not "an instant
missing a label" (§3.4). Because the write path is proven, `AT TIME ZONE
'UTC'` here is not a reinterpretation of ambiguous data; it attaches the
one label the data has always actually had:

    ALTER TABLE audit_logs
      ALTER COLUMN created_at TYPE timestamptz
      USING created_at AT TIME ZONE 'UTC';

This is deliberately NOT `created_at::timestamptz` (a bare cast) -- a bare
cast asks PostgreSQL to apply the *session's* current timezone setting,
which is neither known nor tied to how the value was actually written.

`borrow_transactions.due_at` is explicitly EXCLUDED (§3.4a) -- its historical
values were accepted verbatim from a pre-PR7a client-supplied API field with
no server-side timezone normalization, so there is no evidence of what
timezone any given row's value represents. Converting it would fabricate a
fact this document cannot support. `due_at` remains untouched, naive, by
design -- not an oversight.

**Verify-and-no-op, not blind transformation (§8.7/§8.7a).** `0001_initial.py`
bootstraps a fresh database via `Base.metadata.create_all()` against
*current* ORM metadata. Because this migration's companion ORM change
(`DateTime(timezone=True)` on all five columns, app/models/audit.py,
notification.py, equipment.py, transaction.py) lands in the same commit, a
fresh install already produces `timestamptz` for all five columns before
this migration ever runs. This migration must therefore never assume the
"before" (naive) state -- it inspects `information_schema.columns.data_type`
for each column immediately before acting, and classifies it into exactly
one of three outcomes:

  1. Naive (`timestamp without time zone`) -- needs transformation: run the
     `ALTER ... USING ... AT TIME ZONE 'UTC'` expression above.
  2. Already `timestamp with time zone` -- already at target state: no-op,
     log and return. **Critically, this migration must NEVER re-run the
     `AT TIME ZONE 'UTC'` expression against a column already `timestamptz`**
     -- applied a second time, PostgreSQL first renders the aware value as a
     naive UTC wall-clock representation, and the implicit cast back to
     `timestamptz` that follows (required because the target type is
     `timestamptz`) is then resolved using whatever timezone setting is in
     effect for the *migration session* -- not a fixed, predictable shift,
     but a session-timezone-dependent one. Verify-and-no-op removes this
     risk entirely by never depending on session timezone in the first
     place, rather than reasoning about what it might be (§8.7a/§10).
  3. Anything else (e.g. a bare `date`, `text`, or other unexpected type) --
     fails closed: raises `RuntimeError` naming the column and the
     unexpected type found. Never silently coerced or ignored.

Both the fresh-install path (already-`timestamptz`, outcome 2) and the
historical-upgrade path (`0011 -> head`, naive, outcome 1) converge on the
identical final schema -- verified by an automated regression test rehearsing
both paths (§8.5/§11), not merely asserted here.

**Downgrade** reverses the conversion via the exact inverse expression
(`ALTER COLUMN ... TYPE timestamp USING ... AT TIME ZONE 'UTC'`, §3.4),
value-lossless for the stored instant. Downgrade applies the same
verify-and-no-op discipline: it only acts on a column it finds as
`timestamptz`, and no-ops if already naive (e.g. downgrade run twice).
No data-loss risk (§8.4); the only limitation is a documented
forward-compatibility caveat (§3.6): a value downgraded back to naive and
later re-upgraded is indistinguishable from a value that was always UTC,
which is true for all five of these columns by construction, so this is not
a practical concern for this migration specifically.

This migration also bundles three accompanying Python-only call-site fixes
(no migration needed on their own, fixing the same class of bug):
`app/services/auth_service.py::last_login_at`,
`app/crud/transaction.py::returned_at` (the write inside `close()`),
`app/crud/equipment.py::soft_delete()::deleted_at` -- all changed from
`datetime.utcnow()` to `datetime.now(timezone.utc)`.

Only ever runs against PostgreSQL in this project (see 0002/0004/0011's
identical dialect-gated pattern) -- the SQLite test/dev path never runs
Alembic migrations at all; `tests/conftest.py` builds its schema directly
from ORM metadata.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_timezone_conversion"
down_revision: Union[str, None] = "0011_pagination_ordering_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column) pairs converting in this migration. `due_at` is
# deliberately absent -- see this module's docstring / §3.4a.
_CONVERTING_COLUMNS: tuple[tuple[str, str], ...] = (
    ("audit_logs", "created_at"),
    ("notifications", "created_at"),
    ("equipment_status_history", "changed_at"),
    ("borrow_transactions", "borrowed_at"),
    ("borrow_transactions", "returned_at"),
)

_NAIVE = "timestamp without time zone"
_AWARE = "timestamp with time zone"


def _column_data_type(bind, *, table: str, column: str) -> str:
    data_type = bind.execute(
        sa.text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    ).scalar_one_or_none()

    if data_type is None:
        raise RuntimeError(
            f"Migration 0012 aborted: column '{table}.{column}' does not exist in the "
            "PostgreSQL catalog. This migration expects it to already exist (added by an "
            "earlier migration) -- refusing to silently continue against an unexpected schema."
        )
    return data_type


def _convert_to_timestamptz(bind, *, table: str, column: str) -> None:
    """Classifies (table, column) into needs-transformation / already-target
    / fails-closed (§8.7a) and acts accordingly. Never runs the
    `AT TIME ZONE 'UTC'` upgrade expression against a column already
    `timestamptz` -- see this module's docstring for why that matters."""
    data_type = _column_data_type(bind, table=table, column=column)

    if data_type == _NAIVE:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE timestamptz "
            f"USING {column} AT TIME ZONE 'UTC'"
        )
        return

    if data_type == _AWARE:
        # Already at target state (e.g. a fresh install whose 0001 bootstrap
        # already produced timestamptz from the post-ORM-fix metadata) --
        # intentional no-op, not a degraded path. See §8.7a outcome 2.
        return

    raise RuntimeError(
        f"Migration 0012 aborted: column '{table}.{column}' has unexpected type "
        f"'{data_type}' (expected '{_NAIVE}' or '{_AWARE}'). Refusing to guess how to "
        "convert it -- inspect and resolve manually before re-running this migration."
    )


def _convert_to_naive(bind, *, table: str, column: str) -> None:
    """Downgrade counterpart of `_convert_to_timestamptz` -- same
    verify-and-no-op discipline, reverse direction."""
    data_type = _column_data_type(bind, table=table, column=column)

    if data_type == _AWARE:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE timestamp "
            f"USING {column} AT TIME ZONE 'UTC'"
        )
        return

    if data_type == _NAIVE:
        # Already downgraded (e.g. downgrade run twice) -- no-op.
        return

    raise RuntimeError(
        f"Migration 0012 downgrade aborted: column '{table}.{column}' has unexpected type "
        f"'{data_type}' (expected '{_NAIVE}' or '{_AWARE}'). Refusing to guess how to "
        "convert it -- inspect and resolve manually before re-running this downgrade."
    )


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        # Migrations only ever run against PostgreSQL in this project -- the
        # SQLite test/dev path never runs Alembic at all (see 0002/0004/0011's
        # identical branch). Nothing to do on any other dialect.
        return

    for table, column in _CONVERTING_COLUMNS:
        _convert_to_timestamptz(bind, table=table, column=column)


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        return

    for table, column in reversed(_CONVERTING_COLUMNS):
        _convert_to_naive(bind, table=table, column=column)
