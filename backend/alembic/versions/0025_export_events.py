"""Roadmap PR25B: read-only export API -- outbox, counter, machine keys

Revision ID: 0025_export_events
Revises: 0024_login_lockout
Create Date: 2026-10-13

Purely additive: three new tables (`export_events`, `export_event_counter`,
`export_api_keys`). No existing table or row is modified.

**Backfill.** Every existing dispatch becomes a `dispatch` event and every
closed transaction with a `returned_at` becomes a `receipt` event, numbered
1..N in (event time, transaction id, type) order so a consumer starting at
`after=0` replays history chronologically. The counter is set to N. A consumer
that wants no history calls `GET /export/cursor` ("from now") or
`GET /export/cursor?at=<instant>`. Backfill is idempotent: it runs only when
`export_events` is empty.

**Fresh-install vs. historical-upgrade convergence**, following 0023/0024.
`app.models.export` is registered in `app/db/base.py`, so `0001_initial`'s
`Base.metadata.create_all()` creates these tables on a brand-new install;
`CREATE TABLE IF NOT EXISTS` below creates them for a database that applied
0001-0024 earlier, and `_verify_schema_convergence()` fails closed if the two
paths disagree on type, nullability or catalog default. The counter's
`server_default` exists on the model for exactly that reason.

Only runs raw SQL against PostgreSQL (dialect-gated like 0002-0024); SQLite
tests build these tables from ORM metadata.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025_export_events"
down_revision: Union[str, None] = "0024_login_lockout"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CREATE = [
    """
    CREATE TABLE IF NOT EXISTS export_event_counter (
        id INTEGER NOT NULL,
        last_seq BIGINT NOT NULL DEFAULT 0,
        CONSTRAINT pk_export_event_counter PRIMARY KEY (id),
        CONSTRAINT ck_export_event_counter_singleton CHECK (id = 1)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS export_events (
        seq BIGINT NOT NULL,
        event_id UUID NOT NULL,
        event_type VARCHAR(20) NOT NULL,
        transaction_id UUID NOT NULL,
        event_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        PRIMARY KEY (seq),
        CONSTRAINT uq_export_events_event_id UNIQUE (event_id),
        CONSTRAINT uq_export_events_transaction_type UNIQUE (transaction_id, event_type),
        CONSTRAINT ck_export_events_event_type CHECK (event_type IN ('dispatch', 'receipt')),
        FOREIGN KEY (transaction_id) REFERENCES borrow_transactions (id) ON DELETE RESTRICT
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_export_events_event_at ON export_events (event_at)",
    """
    CREATE TABLE IF NOT EXISTS export_api_keys (
        id UUID NOT NULL,
        name VARCHAR(100) NOT NULL,
        key_hash VARCHAR(64) NOT NULL,
        key_prefix VARCHAR(16) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        created_by_user_id UUID REFERENCES users (id) ON DELETE RESTRICT,
        revoked_at TIMESTAMP WITH TIME ZONE,
        revoked_by_user_id UUID REFERENCES users (id) ON DELETE RESTRICT,
        last_used_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        CONSTRAINT uq_export_api_keys_key_hash UNIQUE (key_hash)
    )
    """,
]

_BACKFILL = """
INSERT INTO export_events (seq, event_id, event_type, transaction_id, event_at)
SELECT row_number() OVER (ORDER BY event_at, transaction_id, event_type),
       gen_random_uuid(), event_type, transaction_id, event_at
FROM (
    SELECT id AS transaction_id, 'dispatch' AS event_type, borrowed_at AS event_at
    FROM borrow_transactions
    UNION ALL
    SELECT id, 'receipt', returned_at
    FROM borrow_transactions
    WHERE status = 'closed' AND returned_at IS NOT NULL
) e
"""

_SET_COUNTER = """
INSERT INTO export_event_counter (id, last_seq)
VALUES (1, (SELECT COALESCE(MAX(seq), 0) FROM export_events))
ON CONFLICT (id) DO UPDATE
SET last_seq = GREATEST(export_event_counter.last_seq, EXCLUDED.last_seq)
"""

_DROP = [
    "DROP TABLE IF EXISTS export_api_keys",
    "DROP TABLE IF EXISTS export_events",
    "DROP TABLE IF EXISTS export_event_counter",
]

# (table, column) -> (data_type, is_nullable, column_default_contains|None)
_EXPECTED = {
    ("export_event_counter", "id"): ("integer", "NO", None),
    ("export_event_counter", "last_seq"): ("bigint", "NO", "0"),
    ("export_events", "seq"): ("bigint", "NO", None),
    ("export_events", "event_id"): ("uuid", "NO", None),
    ("export_events", "event_type"): ("character varying", "NO", None),
    ("export_events", "transaction_id"): ("uuid", "NO", None),
    ("export_events", "event_at"): ("timestamp with time zone", "NO", None),
    ("export_events", "created_at"): ("timestamp with time zone", "NO", "now()"),
    ("export_api_keys", "id"): ("uuid", "NO", None),
    ("export_api_keys", "name"): ("character varying", "NO", None),
    ("export_api_keys", "key_hash"): ("character varying", "NO", None),
    ("export_api_keys", "key_prefix"): ("character varying", "NO", None),
    ("export_api_keys", "created_at"): ("timestamp with time zone", "NO", "now()"),
    ("export_api_keys", "created_by_user_id"): ("uuid", "YES", None),
    ("export_api_keys", "revoked_at"): ("timestamp with time zone", "YES", None),
    ("export_api_keys", "revoked_by_user_id"): ("uuid", "YES", None),
    ("export_api_keys", "last_used_at"): ("timestamp with time zone", "YES", None),
}

_COLUMN_SQL = sa.text(
    """
    SELECT data_type, is_nullable, column_default
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = :table AND column_name = :column
    """
)


def _verify_schema_convergence() -> None:
    """Fail closed if the historical-upgrade path produced columns the
    fresh-install path would not have."""
    bind = op.get_bind()
    for (table, column), (exp_type, exp_nullable, exp_default) in _EXPECTED.items():
        row = bind.execute(_COLUMN_SQL, {"table": table, "column": column}).fetchone()
        if row is None:
            raise RuntimeError(f"{table}.{column} is missing after this migration.")
        data_type, is_nullable, column_default = row
        if data_type != exp_type:
            raise RuntimeError(f"{table}.{column} has data_type {data_type!r}, expected {exp_type!r}.")
        if is_nullable != exp_nullable:
            raise RuntimeError(f"{table}.{column} is_nullable is {is_nullable!r}, expected {exp_nullable!r}.")
        if exp_default is None:
            if column_default is not None:
                raise RuntimeError(f"{table}.{column} has unexpected catalog default {column_default!r}.")
        elif column_default is None or exp_default not in str(column_default):
            raise RuntimeError(
                f"{table}.{column} default is {column_default!r}, expected it to contain {exp_default!r}."
            )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for statement in _CREATE:
        op.execute(sa.text(statement))
    _verify_schema_convergence()
    if bind.execute(sa.text("SELECT 1 FROM export_events LIMIT 1")).fetchone() is None:
        op.execute(sa.text(_BACKFILL))
    op.execute(sa.text(_SET_COUNTER))


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for statement in _DROP:
        op.execute(sa.text(statement))
