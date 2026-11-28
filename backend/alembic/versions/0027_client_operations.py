"""Offline-sync idempotency ledger `client_operations` (Roadmap PR25E slice B1)

Revision ID: 0027_client_operations
Revises: 0026_ward_department_phone
Create Date: 2026-10-13

Purely additive: one new table, `client_operations`
(docs/design/PR25D_OFFLINE_OPERATION_PLAN.md sections 6.2, 8.3, 16.1),
including the adoption columns and the pilot-statistics columns. No existing
table or row is modified, nothing is backfilled, and no endpoint writes the
table yet. All foreign keys are ON DELETE RESTRICT.

**Fresh-install vs. historical-upgrade convergence**, following 0023-0026.
`app.models.client_operation` is registered in `app/db/base.py`, so
`0001_initial`'s `Base.metadata.create_all()` creates the table on a brand-new
install; `CREATE TABLE IF NOT EXISTS` below creates it for a database that
applied 0001-0026, and `_verify_schema_convergence()` fails closed if the
catalog does not match (types, nullability, catalog defaults, FK delete
rules). The `server_default`s exist on the model for exactly that reason.

Only runs raw SQL against PostgreSQL (dialect-gated like 0002-0026); SQLite
tests build the table from ORM metadata.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027_client_operations"
down_revision: Union[str, None] = "0026_ward_department_phone"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CREATE = [
    """
    CREATE TABLE IF NOT EXISTS client_operations (
        op_id UUID NOT NULL,
        device_id UUID NOT NULL,
        device_seq BIGINT NOT NULL,
        user_id UUID NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
        submitted_by_user_id UUID REFERENCES users (id) ON DELETE RESTRICT,
        adopted_at TIMESTAMP WITH TIME ZONE,
        stale_context BOOLEAN NOT NULL DEFAULT false,
        op_type VARCHAR(20) NOT NULL,
        payload_hash VARCHAR(64) NOT NULL,
        transaction_id UUID REFERENCES borrow_transactions (id) ON DELETE RESTRICT,
        status VARCHAR(20) NOT NULL,
        result_code VARCHAR(64),
        occurred_at TIMESTAMP WITH TIME ZONE,
        occurred_at_local TIMESTAMP WITH TIME ZONE,
        clock_offset_ms BIGINT,
        first_seen_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        time_flag VARCHAR(30),
        received_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
        attempt_count INTEGER NOT NULL DEFAULT 1,
        payload JSONB NOT NULL,
        resolved_by UUID REFERENCES users (id) ON DELETE RESTRICT,
        resolved_at TIMESTAMP WITH TIME ZONE,
        resolution VARCHAR(30),
        resolution_note TEXT,
        collision_group_id UUID,
        order_valid_at_detection BOOLEAN,
        proposed_sequence JSONB,
        bands_overlap BOOLEAN,
        offset_age_s INTEGER,
        resolution_matches_proposal VARCHAR(20),
        PRIMARY KEY (op_id),
        CONSTRAINT uq_client_operations_device_seq UNIQUE (device_id, device_seq),
        CONSTRAINT ck_client_operations_op_type CHECK (op_type IN ('dispatch', 'receipt')),
        CONSTRAINT ck_client_operations_status CHECK (status IN ('pending', 'applied', 'conflict', 'rejected', 'resolved')),
        CONSTRAINT ck_client_operations_time_flag CHECK (time_flag IS NULL OR time_flag IN ('clamped_future', 'clamped_old', 'before_dispatch', 'before_last_receipt')),
        CONSTRAINT ck_client_operations_resolution_matches CHECK (resolution_matches_proposal IS NULL OR resolution_matches_proposal IN ('same', 'different', 'dismissed_only')),
        CONSTRAINT ck_client_operations_attempt_count CHECK (attempt_count >= 1)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_client_operations_status_received_at ON client_operations (status, received_at)",
    "CREATE INDEX IF NOT EXISTS ix_client_operations_received_at ON client_operations (received_at)",
    "CREATE INDEX IF NOT EXISTS ix_client_operations_transaction_id ON client_operations (transaction_id)",
    "CREATE INDEX IF NOT EXISTS ix_client_operations_collision_group_id ON client_operations (collision_group_id)",
]

_DROP = ["DROP TABLE IF EXISTS client_operations"]

_TS = "timestamp with time zone"
# column -> (data_type, is_nullable, column_default_contains|None)
_EXPECTED = {
    "op_id": ("uuid", "NO", None),
    "device_id": ("uuid", "NO", None),
    "device_seq": ("bigint", "NO", None),
    "user_id": ("uuid", "NO", None),
    "submitted_by_user_id": ("uuid", "YES", None),
    "adopted_at": (_TS, "YES", None),
    "stale_context": ("boolean", "NO", "false"),
    "op_type": ("character varying", "NO", None),
    "payload_hash": ("character varying", "NO", None),
    "transaction_id": ("uuid", "YES", None),
    "status": ("character varying", "NO", None),
    "result_code": ("character varying", "YES", None),
    "occurred_at": (_TS, "YES", None),
    "occurred_at_local": (_TS, "YES", None),
    "clock_offset_ms": ("bigint", "YES", None),
    "first_seen_at": (_TS, "NO", "now()"),
    "time_flag": ("character varying", "YES", None),
    "received_at": (_TS, "NO", "now()"),
    "attempt_count": ("integer", "NO", "1"),
    "payload": ("jsonb", "NO", None),
    "resolved_by": ("uuid", "YES", None),
    "resolved_at": (_TS, "YES", None),
    "resolution": ("character varying", "YES", None),
    "resolution_note": ("text", "YES", None),
    "collision_group_id": ("uuid", "YES", None),
    "order_valid_at_detection": ("boolean", "YES", None),
    "proposed_sequence": ("jsonb", "YES", None),
    "bands_overlap": ("boolean", "YES", None),
    "offset_age_s": ("integer", "YES", None),
    "resolution_matches_proposal": ("character varying", "YES", None),
}

_COLUMN_SQL = sa.text(
    """
    SELECT column_name, data_type, is_nullable, column_default
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'client_operations'
    """
)

_FK_SQL = sa.text(
    """
    SELECT confdeltype::text FROM pg_constraint
    WHERE conrelid = 'public.client_operations'::regclass AND contype = 'f'
    """
)


def _verify_schema_convergence() -> None:
    """Fail closed if the historical-upgrade path produced a table the
    fresh-install path would not have."""
    bind = op.get_bind()
    actual = {r[0]: r[1:] for r in bind.execute(_COLUMN_SQL).fetchall()}
    if set(actual) != set(_EXPECTED):
        raise RuntimeError(
            f"client_operations columns differ: missing {sorted(set(_EXPECTED) - set(actual))}, "
            f"unexpected {sorted(set(actual) - set(_EXPECTED))}."
        )
    for column, (exp_type, exp_nullable, exp_default) in _EXPECTED.items():
        data_type, is_nullable, column_default = actual[column]
        if data_type != exp_type:
            raise RuntimeError(f"client_operations.{column} has data_type {data_type!r}, expected {exp_type!r}.")
        if is_nullable != exp_nullable:
            raise RuntimeError(f"client_operations.{column} is_nullable is {is_nullable!r}, expected {exp_nullable!r}.")
        if exp_default is None:
            if column_default is not None:
                raise RuntimeError(f"client_operations.{column} has unexpected catalog default {column_default!r}.")
        elif column_default is None or exp_default not in str(column_default):
            raise RuntimeError(
                f"client_operations.{column} default is {column_default!r}, expected it to contain {exp_default!r}."
            )
    fk_rules = [r[0] for r in bind.execute(_FK_SQL).fetchall()]
    if len(fk_rules) != 4 or any(rule != "r" for rule in fk_rules):
        raise RuntimeError(f"client_operations must have exactly 4 ON DELETE RESTRICT foreign keys, found {fk_rules!r}.")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for statement in _CREATE:
        op.execute(sa.text(statement))
    _verify_schema_convergence()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for statement in _DROP:
        op.execute(sa.text(statement))
