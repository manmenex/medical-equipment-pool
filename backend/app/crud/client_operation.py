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

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import audit as audit_crud
from app.models.client_operation import (
    OP_STATUS_APPLIED,
    OP_STATUS_CONFLICT,
    OP_STATUS_PENDING,
    OP_STATUS_RESOLVED,
    ClientOperation,
)

AUDIT_ACTION_SYNC_CONFLICT_RESOLVED = "sync_conflict_resolved"
AUDIT_ACTION_SYNC_ADOPT = "sync_adopt"
AUDIT_ENTITY_CLIENT_OPERATION = "client_operation"
RESOLUTION_DISMISSED = "dismissed"
RESOLUTION_APPLIED_AS = "applied_as"
RESULT_CODE_RESOLVER_APPLIED = "RESOLVER_APPLIED"


def reviewable_clause(pending_cutoff: datetime):
    """Rows a human may act on: ``conflict``, or ``pending`` whose 48 h
    dependency window (measured from ``first_seen_at``) has run out."""
    return or_(
        ClientOperation.status == OP_STATUS_CONFLICT,
        and_(ClientOperation.status == OP_STATUS_PENDING, ClientOperation.first_seen_at <= pending_cutoff),
    )


@dataclass(frozen=True)
class ResolveLink:
    """Slice B4 apply-now: the new, resolver-originated operation closes the
    original review row in the SAME database transaction as the business
    write (docs/design/PR25D_OFFLINE_OPERATION_PLAN.md section 9.6)."""

    original_op_id: uuid.UUID
    original_user_id: uuid.UUID
    original_device_id: uuid.UUID
    resolver_user_id: uuid.UUID
    pending_cutoff: datetime
    resolved_at: datetime
    prior_status: str
    prior_result_code: str | None
    ip_address: str | None = None
    user_agent: str | None = None


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
    # Slice B2b: set by the sync layer after the section 11 time guards.
    time_flag: str | None = None
    # Slice B4: set only for an Apply-now by a resolver.
    resolves: "ResolveLink | None" = None
    # Apply-now of a conflicted dispatch: the transaction must keep the
    # ORIGINAL op_id as its id (offline receipts reference it), while
    # ``op_id`` stays the id of the new ledger row.
    transaction_id_override: uuid.UUID | None = None
    # Set only when no business time is applied (too_old conflict): the
    # unclamped adjusted time stored in the ledger for the reviewer.
    occurred_at: datetime | None = None
    # Slice B2c: set only for an adopted op (section 8.3) / a stale snapshot.
    adopted_at: datetime | None = None
    stale_context: bool = False

    def audit_fields(self) -> dict[str, str | int | bool]:
        fields: dict[str, str | int | bool] = {
            "op_id": str(self.op_id),
            "device_id": str(self.device_id),
            "device_seq": self.device_seq,
        }
        if self.resolves is not None:
            fields.update(
                {
                    "applied_by_resolver": True,
                    "resolves_op_id": str(self.resolves.original_op_id),
                    "original_user_id": str(self.user_id),
                    "submitted_by_user_id": str(self.submitted_by_user_id),
                }
            )
        if self.adopted_at is not None:
            fields.update(
                {
                    "adopted": True,
                    "original_user_id": str(self.user_id),
                    "submitted_by_user_id": str(self.submitted_by_user_id),
                }
            )
        return fields


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
                time_flag=ctx.time_flag,
                submitted_by_user_id=ctx.submitted_by_user_id,
                adopted_at=ctx.adopted_at,
                stale_context=ctx.stale_context,
                attempt_count=ClientOperation.attempt_count + 1,
            )
        )
        won = (await db.execute(stmt)).rowcount == 1
        if not won:
            await db.rollback()
            raise ClientOpAlreadyProcessedError()
        await _audit_adopt(db, ctx)
        return

    if ctx.resolves is not None:
        await _close_original(db, ctx, transaction_id)

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
            result_code=RESULT_CODE_RESOLVER_APPLIED if ctx.resolves is not None else None,
            occurred_at=occurred_at,
            time_flag=ctx.time_flag,
            adopted_at=ctx.adopted_at,
            stale_context=ctx.stale_context,
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
    await _audit_adopt(db, ctx)


async def _audit_adopt(db: AsyncSession, ctx: ClientOpContext) -> None:
    """Section 8.3: the ``sync_adopt`` audit entry, written in the same
    transaction as the business write and the ledger row. Actor = adopter;
    the original operator is data (``original_user_ids``)."""
    if ctx.adopted_at is None:
        return
    await audit_crud.create(
        db,
        user_id=ctx.submitted_by_user_id,
        action=AUDIT_ACTION_SYNC_ADOPT,
        entity_type=AUDIT_ENTITY_CLIENT_OPERATION,
        entity_id=ctx.op_id,
        after_data={
            "original_user_ids": [str(ctx.user_id)],
            "submitted_by_user_id": str(ctx.submitted_by_user_id),
            "device_id": str(ctx.device_id),
            "op_ids": [str(ctx.op_id)],
            "count": 1,
            "adopted_at": ctx.adopted_at.isoformat(),
        },
    )


async def _close_original(db: AsyncSession, ctx: ClientOpContext, transaction_id: uuid.UUID) -> None:
    """Conditional ``conflict|expired-pending -> resolved`` UPDATE of the
    original row, decided by affected-row count (the PR8A shape): of two
    concurrent resolvers exactly one gets 1 row; the other rolls the whole
    business write back. Writes the single ``sync_conflict_resolved`` audit
    entry (flush only; the service owns the commit)."""
    link = ctx.resolves
    assert link is not None
    won = (
        await db.execute(
            update(ClientOperation)
            .where(ClientOperation.op_id == link.original_op_id, reviewable_clause(link.pending_cutoff))
            .values(
                status=OP_STATUS_RESOLVED,
                resolution=RESOLUTION_APPLIED_AS,
                resolved_by=link.resolver_user_id,
                resolved_at=link.resolved_at,
                resolution_note=str(ctx.op_id),
                transaction_id=transaction_id,
            )
        )
    ).rowcount == 1
    if not won:
        await db.rollback()
        raise ClientOpAlreadyProcessedError()
    await audit_crud.create(
        db,
        user_id=link.resolver_user_id,
        action=AUDIT_ACTION_SYNC_CONFLICT_RESOLVED,
        entity_type=AUDIT_ENTITY_CLIENT_OPERATION,
        entity_id=link.original_op_id,
        before_data={"status": link.prior_status, "result_code": link.prior_result_code},
        after_data={
            "status": OP_STATUS_RESOLVED,
            "resolution": RESOLUTION_APPLIED_AS,
            "resolver_user_id": str(link.resolver_user_id),
            "original_user_id": str(link.original_user_id),
            "device_id": str(link.original_device_id),
            "original_op_id": str(link.original_op_id),
            "new_op_id": str(ctx.op_id),
            "transaction_id": str(transaction_id),
        },
        ip_address=link.ip_address,
        user_agent=link.user_agent,
    )


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
            .values(
                status=status,
                result_code=result_code,
                occurred_at=ctx.occurred_at,
                time_flag=ctx.time_flag,
                submitted_by_user_id=ctx.submitted_by_user_id,
                adopted_at=ctx.adopted_at,
                stale_context=ctx.stale_context,
                attempt_count=ClientOperation.attempt_count + 1,
            )
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
                    occurred_at=ctx.occurred_at,
                    time_flag=ctx.time_flag,
                    adopted_at=ctx.adopted_at,
                    stale_context=ctx.stale_context,
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
