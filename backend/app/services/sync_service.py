"""Roadmap PR25E slice B2 -- ``POST /sync/operations`` per-operation engine
(docs/design/PR25D_OFFLINE_OPERATION_PLAN.md sections 6.3 and 9).

This module owns *request* bookkeeping only (the ``client_operations`` ledger
and the result vocabulary). Every lifecycle change goes through
``borrow_service.borrow`` / ``return_equipment``; nothing here touches
equipment or transaction state directly.

Each operation runs in its own database transaction. A domain failure never
leaves a half-applied operation: the session is rolled back explicitly, the
ledger is re-read (a concurrent duplicate may have won), and only then is a
``conflict`` row written in a separate small transaction.
"""
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    DomainError,
    EquipmentNotAvailableError,
    EquipmentNotFoundError,
    InvalidInputError,
    ReceiptRaceLostError,
    TransactionAlreadyReturnedError,
    TransactionNotFoundError,
)
from app.crud import client_operation as client_op_crud
from app.models.client_operation import (
    OP_STATUS_APPLIED,
    OP_STATUS_CONFLICT,
    OP_STATUS_PENDING,
    OP_STATUS_REJECTED,
    OP_STATUS_RESOLVED,
    ClientOperation,
)
from app.schemas.sync import (
    OP_TYPE_DISPATCH,
    RESULT_APPLIED,
    RESULT_CONFLICT,
    RESULT_DUPLICATE,
    RESULT_REJECTED,
    RESULT_RETRY_LATER,
    SyncOperation,
    SyncOpResult,
)
from app.services import borrow_service

@dataclass(frozen=True)
class Actor:
    """The authenticated user, reduced to its id. Each operation may roll the
    session back, which expires ORM instances; an id survives that."""

    id: uuid.UUID


CODE_APPLIED = "APPLIED"
CODE_DUPLICATE = "DUPLICATE"
CODE_USER_MISMATCH = "OP_USER_MISMATCH"
CODE_ID_REUSED = "OP_ID_REUSED"
CODE_DEVICE_SEQ_REUSED = "DEVICE_SEQ_REUSED"
CODE_DEPENDENCY_MISSING = "DEPENDENCY_MISSING"

# Section 9.1 item 4: a receipt for an unknown transaction is retried for this
# long, measured from the server's first sight of the op_id.
DEPENDENCY_WINDOW = timedelta(hours=48)

# Domain errors that mean "the request was understood but the current state
# does not allow it" (section 6.3 step 4).
_CONFLICT_ERRORS = (
    EquipmentNotAvailableError,
    TransactionAlreadyReturnedError,
    ReceiptRaceLostError,
    InvalidInputError,
    EquipmentNotFoundError,
    TransactionNotFoundError,
)

_MESSAGES = {
    CODE_USER_MISMATCH: "This operation cannot be submitted by the current user.",
    CODE_ID_REUSED: "This op_id was already used with different content.",
    CODE_DEVICE_SEQ_REUSED: "This device_seq was already used by a different operation.",
    CODE_DEPENDENCY_MISSING: "The referenced transaction is not known yet; try again later.",
}


def payload_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _result(op: SyncOperation, result: str, code: str, *, transaction_id: uuid.UUID | None = None, message: str | None = None) -> SyncOpResult:
    return SyncOpResult(
        op_id=op.op_id,
        result=result,
        code=code,
        transaction_id=transaction_id,
        message=message or _MESSAGES.get(code, code),
    )


def _mismatch(op: SyncOperation) -> SyncOpResult:
    # Deliberately identical for "row exists, not yours" and "envelope names
    # someone else": it must reveal nothing about any stored row.
    return _result(op, RESULT_REJECTED, CODE_USER_MISMATCH)


def _from_ledger_row(op: SyncOperation, row: ClientOperation, user: Actor, digest: str) -> SyncOpResult | None:
    """Section 6.3 step 1 for an existing row. ``None`` means "execute it":
    a ``pending`` row is never a terminal answer."""
    if user.id not in (row.user_id, row.submitted_by_user_id):
        return _mismatch(op)
    if row.payload_hash != digest:
        return _result(op, RESULT_REJECTED, CODE_ID_REUSED)
    if row.status in (OP_STATUS_APPLIED, OP_STATUS_RESOLVED):
        return _result(op, RESULT_DUPLICATE, CODE_DUPLICATE, transaction_id=row.transaction_id, message="Already recorded.")
    if row.status == OP_STATUS_CONFLICT:
        return _result(op, RESULT_CONFLICT, row.result_code or "CONFLICT", message="Awaiting review.")
    if row.status == OP_STATUS_REJECTED:
        return _result(op, RESULT_REJECTED, row.result_code or "REJECTED", message="Previously rejected.")
    return None


async def _seq_clash(db: AsyncSession, op: SyncOperation) -> bool:
    other = await client_op_crud.get_by_device_seq(db, op.device_id, op.device_seq)
    return other is not None and other.op_id != op.op_id


async def _settle(db: AsyncSession, op: SyncOperation, user: Actor, digest: str) -> SyncOpResult | None:
    """Re-read the ledger after a failed attempt (session already rolled
    back). Returns the stored answer, or None when only a ``pending`` row /
    no row exists."""
    row = await client_op_crud.get(db, op.op_id)
    if row is not None:
        return _from_ledger_row(op, row, user, digest)
    if await _seq_clash(db, op):
        return _result(op, RESULT_REJECTED, CODE_DEVICE_SEQ_REUSED)
    return None


def _context(op: SyncOperation, user: Actor, digest: str, *, pending: bool) -> client_op_crud.ClientOpContext:
    return client_op_crud.ClientOpContext(
        op_id=op.op_id,
        device_id=op.device_id,
        device_seq=op.device_seq,
        user_id=user.id,
        submitted_by_user_id=user.id,
        op_type=op.op_type,
        payload_hash=digest,
        payload=op.business_payload(),
        occurred_at_local=op.occurred_at_local,
        clock_offset_ms=op.clock_offset_ms,
        pending=pending,
    )


async def _stored_result(db: AsyncSession, op: SyncOperation, user: Actor, digest: str) -> SyncOpResult:
    """Return whatever the ledger now holds for this op (after a write that
    a racing winner may have beaten)."""
    row = await client_op_crud.get(db, op.op_id)
    if row is not None:
        res = _from_ledger_row(op, row, user, digest)
        if res is not None:
            return res
        return _result(op, RESULT_RETRY_LATER, row.result_code or CODE_DEPENDENCY_MISSING)
    return _result(op, RESULT_RETRY_LATER, CODE_DEPENDENCY_MISSING)


async def _execute(
    db: AsyncSession, op: SyncOperation, user: Actor, ctx: client_op_crud.ClientOpContext, ip: str | None, ua: str | None
):
    if op.op_type == OP_TYPE_DISPATCH:
        d = op.dispatch
        return await borrow_service.borrow(
            db,
            equipment_id=d.equipment_id,
            borrower_user_id=user.id,
            ward_id=d.ward_id,
            dispatch_type=d.dispatch_type,
            routine_round=d.routine_round,
            department_id=d.department_id,
            phone_number=d.phone_number,
            pickup_location_id=d.pickup_location_id,
            dropoff_location_id=d.dropoff_location_id,
            notes=d.notes,
            ip_address=ip,
            user_agent=ua,
            actor_user_id=user.id,
            client_op=ctx,
        )
    r = op.receipt
    return await borrow_service.return_equipment(
        db,
        transaction_id=r.transaction_id,
        receipt_outcome=r.receipt_outcome,
        notes=r.notes,
        received_by_user_id=user.id,
        ip_address=ip,
        user_agent=ua,
        actor_user_id=user.id,
        client_op=ctx,
    )


async def process_operation(
    db: AsyncSession, op: SyncOperation, user, *, ip_address: str | None = None, user_agent: str | None = None
) -> SyncOpResult:
    user = Actor(user.id)
    digest = payload_hash(op.business_payload())

    # Step 1: user check FIRST, before anything else is revealed.
    row = await client_op_crud.get(db, op.op_id)
    if row is None and op.user_id != user.id:
        return _mismatch(op)
    existing_pending = False
    first_seen: datetime | None = None
    if row is not None:
        res = _from_ledger_row(op, row, user, digest)
        if res is not None:
            return res
        if op.user_id != user.id:
            return _mismatch(op)
        existing_pending = True
        first_seen = row.first_seen_at
    else:
        if await _seq_clash(db, op):
            return _result(op, RESULT_REJECTED, CODE_DEVICE_SEQ_REUSED)

    # Step 2: execute through the lifecycle service (ledger write inside it).
    ctx = _context(op, user, digest, pending=existing_pending)
    try:
        tx = await _execute(db, op, user, ctx, ip_address, user_agent)
    except (client_op_crud.ClientOpAlreadyProcessedError, client_op_crud.ClientOpLedgerConflictError):
        # The service rolled back; someone else owns this op_id / device_seq.
        res = await _settle(db, op, user, digest)
        return res or _result(op, RESULT_RETRY_LATER, CODE_DEPENDENCY_MISSING)
    except DomainError as exc:
        # Step 4(a): never assume the service rolled back.
        await db.rollback()
        if not isinstance(exc, _CONFLICT_ERRORS):
            return _result(op, RESULT_REJECTED, exc.code, message=exc.message)
        # 4(b): a racing winner (or stored outcome) beats this error.
        res = await _settle(db, op, user, digest)
        if res is not None:
            return res
        return await _record_failure(db, op, user, ctx, digest, exc, existing_pending, first_seen)
    except Exception:
        await db.rollback()
        raise

    return _result(op, RESULT_APPLIED, CODE_APPLIED, transaction_id=tx.id, message="Recorded.")


async def _record_failure(
    db: AsyncSession,
    op: SyncOperation,
    user: Actor,
    ctx: client_op_crud.ClientOpContext,
    digest: str,
    exc: DomainError,
    existing_pending: bool,
    first_seen: datetime | None,
) -> SyncOpResult:
    now = datetime.now(timezone.utc)
    # Section 9.1 item 4: unknown receipt target -> retry_later inside 48 h.
    if isinstance(exc, TransactionNotFoundError) and op.op_type != OP_TYPE_DISPATCH:
        age = now - (first_seen if first_seen is not None else now)
        if age < DEPENDENCY_WINDOW:
            if existing_pending:
                await client_op_crud.bump_pending_attempt(db, op.op_id)
            else:
                await client_op_crud.record_outcome(
                    db, ctx, status=OP_STATUS_PENDING, result_code=CODE_DEPENDENCY_MISSING, existing_pending=False
                )
            return await _stored_result(db, op, user, digest)
    await client_op_crud.record_outcome(
        db, ctx, status=OP_STATUS_CONFLICT, result_code=exc.code, existing_pending=existing_pending
    )
    # Re-read: a racing winner always beats this conflict row.
    return await _stored_result_for_failure(db, op, user, digest, exc)


async def _stored_result_for_failure(
    db: AsyncSession, op: SyncOperation, user: Actor, digest: str, exc: DomainError
) -> SyncOpResult:
    row = await client_op_crud.get(db, op.op_id)
    if row is not None:
        res = _from_ledger_row(op, row, user, digest)
        if res is not None:
            return res
    return _result(op, RESULT_CONFLICT, exc.code, message=exc.message)


async def process_batch(
    db: AsyncSession, operations: list[SyncOperation], user, *, ip_address: str | None, user_agent: str | None
) -> list[SyncOpResult]:
    # Within one device, strictly by device_seq (section 9.1 item 1); the sort
    # is stable, so the order across devices stays as submitted.
    user = Actor(user.id)
    first_index: dict[uuid.UUID, int] = {}
    for i, o in enumerate(operations):
        first_index.setdefault(o.device_id, i)
    ordered = sorted(operations, key=lambda o: (first_index[o.device_id], o.device_seq))
    return [await process_operation(db, o, user, ip_address=ip_address, user_agent=user_agent) for o in ordered]
