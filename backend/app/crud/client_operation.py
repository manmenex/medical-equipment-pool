"""Roadmap PR25E slice B2 -- data access for the ``client_operations`` ledger
(docs/design/PR25D_OFFLINE_OPERATION_PLAN.md section 6.3).

Only ledger bookkeeping lives here. No function in this module touches
equipment or transaction state; the lifecycle stays with
``app.services.borrow_service``.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_operation import (
    OP_STATUS_APPLIED,
    OP_STATUS_PENDING,
    ClientOperation,
)


@dataclass(frozen=True)
class ClientOpContext:
    """What the lifecycle services need to know about a sync-originated
    operation so they can write the ledger row inside their own transaction.

    ``pending`` is True when step 1 of section 6.3 found an existing
    ``pending`` ledger row: the row is then moved to ``applied`` by a
    conditional UPDATE instead of inserted."""

    op_id: uuid.UUID
    device_id: uuid.UUID
    device_seq: int
    user_id: uuid.UUID
    submitted_by_user_id: uuid.UUID
    op_type: str
    payload_hash: str
    payload: dict[str, Any]
    occurred_at_local: datetime | None = None
    clock_offset_ms: int | None = None
    pending: bool = False

    def audit_fields(self) -> dict[str, str | int]:
        return {"op_id": str(self.op_id), "device_id": str(self.device_id), "device_seq": self.device_seq}


class ClientOpAlreadyProcessedError(Exception):
    """The conditional ``pending -> applied`` UPDATE affected zero rows:
    another request already moved the ledger row. The service has rolled the
    session back; the sync layer re-reads the ledger (section 6.3 step 2)."""


class ClientOpLedgerConflictError(Exception):
    """Inserting the ``applied`` ledger row hit a unique violation (op_id PK or
    ``(device_id, device_seq)``). The service has rolled back; the sync layer
    re-reads the ledger to tell a racing duplicate from a reused device_seq."""


async def get(db: AsyncSession, op_id: uuid.UUID) -> ClientOperation | None:
    return (await db.execute(select(ClientOperation).where(ClientOperation.op_id == op_id))).scalar_one_or_none()


async def get_by_device_seq(db: AsyncSession, device_id: uuid.UUID, device_seq: int) -> ClientOperation | None:
    return (
        await db.execute(
            select(ClientOperation).where(
                ClientOperation.device_id == device_id, ClientOperation.device_seq == device_seq
            )
        )
    ).scalar_one_or_none()


async def write_applied(
    db: AsyncSession, ctx: ClientOpContext, *, transaction_id: uuid.UUID, occurred_at: datetime | None
) -> None:
    """Record the op as ``applied`` in the caller's open database transaction
    (flush only; the service owns the commit). Raises
    ``ClientOpAlreadyProcessedError`` / ``ClientOpLedgerConflictError`` after
    rolling the session back."""
    if ctx.pending:
        stmt = (
            update(ClientOperation)
            .where(ClientOperation.op_id == ctx.op_id, ClientOperation.status == OP_STATUS_PENDING)
            .values(
                status=OP_STATUS_APPLIED,
                transaction_id=transaction_id,
                occurred_at=occurred_at,
                result_code=None,
                attempt_count=ClientOperation.attempt_count + 1,
            )
        )
        won = (await db.execute(stmt)).rowcount == 1
        if not won:
            await db.rollback()
            raise ClientOpAlreadyProcessedError()
        return

    db.add(
        ClientOperation(
            op_id=ctx.op_id,
            device_id=ctx.device_id,
            device_seq=ctx.device_seq,
            user_id=ctx.user_id,
            submitted_by_user_id=ctx.submitted_by_user_id,
            op_type=ctx.op_type,
            payload_hash=ctx.payload_hash,
            transaction_id=transaction_id,
            status=OP_STATUS_APPLIED,
            occurred_at=occurred_at,
            occurred_at_local=ctx.occurred_at_local,
            clock_offset_ms=ctx.clock_offset_ms,
            payload=ctx.payload,
        )
    )
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ClientOpLedgerConflictError() from exc


def _insert_do_nothing(db: AsyncSession, values: dict[str, Any]):
    dialect = db.get_bind().dialect.name
    insert_fn = pg_insert if dialect == "postgresql" else sqlite_insert
    return insert_fn(ClientOperation).values(**values).on_conflict_do_nothing()


async def record_outcome(
    db: AsyncSession,
    ctx: ClientOpContext,
    *,
    status: str,
    result_code: str,
    existing_pending: bool,
) -> None:
    """Persist a non-applied outcome (``conflict``/``rejected``/``pending``) in
    its own small transaction (committed here). No lifecycle effect.

    - no existing row: ``INSERT ... ON CONFLICT DO NOTHING`` (a racing winner
      always beats this write);
    - existing ``pending`` row: ``UPDATE ... WHERE status='pending'``.
    The caller re-reads the row afterwards and returns whatever is stored.
    """
    if existing_pending:
        await db.execute(
            update(ClientOperation)
            .where(ClientOperation.op_id == ctx.op_id, ClientOperation.status == OP_STATUS_PENDING)
            .values(status=status, result_code=result_code, attempt_count=ClientOperation.attempt_count + 1)
        )
    else:
        await db.execute(
            _insert_do_nothing(
                db,
                dict(
                    op_id=ctx.op_id,
                    device_id=ctx.device_id,
                    device_seq=ctx.device_seq,
                    user_id=ctx.user_id,
                    submitted_by_user_id=ctx.submitted_by_user_id,
                    op_type=ctx.op_type,
                    payload_hash=ctx.payload_hash,
                    status=status,
                    result_code=result_code,
                    occurred_at_local=ctx.occurred_at_local,
                    clock_offset_ms=ctx.clock_offset_ms,
                    payload=ctx.payload,
                    stale_context=False,
                    attempt_count=1,
                ),
            )
        )
    await db.commit()


async def bump_pending_attempt(db: AsyncSession, op_id: uuid.UUID) -> None:
    """A repeated ``retry_later``: keep the row (and its ``first_seen_at``),
    count the attempt. Commits."""
    await db.execute(
        update(ClientOperation)
        .where(ClientOperation.op_id == op_id, ClientOperation.status == OP_STATUS_PENDING)
        .values(attempt_count=ClientOperation.attempt_count + 1)
    )
    await db.commit()
