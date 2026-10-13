"""Roadmap PR25E slice B4 -- conflict review list, detail and resolution
(docs/design/PR25D_OFFLINE_OPERATION_PLAN.md sections 9.6 and 9.8).

Two resolution actions only:

* **Dismiss** -- the ledger row goes ``conflict -> resolved`` with a reason;
  no business change.
* **Apply now** -- the stored payload is re-run through
  ``borrow_service.borrow`` / ``return_equipment`` as a NEW operation (fresh
  ``op_id``, resolution-time business time, ``actor_user_id`` = resolver,
  recorded operator = the original operator). The original row is closed by
  ``crud.client_operation.write_applied`` inside the service's own
  transaction (conditional UPDATE decided by affected-row count), so the
  business write, the new ledger row, the original's ``resolved`` state, the
  audit entry and exactly one export event commit or roll back together.

This module never touches equipment or transaction state directly, and the
only status writes are the ledger transitions above. Held dependents are a
client-side notion (design 9.1 item 3): once the original row is
``resolved`` the client simply sends them, and they are validated normally.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    DomainError,
    InvalidInputError,
    ResourceNotFoundError,
    SyncApplyFailedError,
    SyncOpNotResolvableError,
    SyncReviewAdminOnlyError,
)
from app.crud import audit as audit_crud
from app.crud import client_operation as client_op_crud
from app.crud.client_operation import (
    AUDIT_ACTION_SYNC_CONFLICT_RESOLVED,
    AUDIT_ENTITY_CLIENT_OPERATION,
    RESOLUTION_DISMISSED,
    ClientOpAlreadyProcessedError,
    ClientOpContext,
    ClientOpLedgerConflictError,
    ResolveLink,
    reviewable_clause,
)
from app.crud import transaction as transaction_crud
from app.models.client_operation import (
    OP_STATUS_CONFLICT,
    OP_STATUS_PENDING,
    OP_STATUS_RESOLVED,
    OP_TYPE_DISPATCH,
    ClientOperation,
)
from app.models.equipment import Equipment, EquipmentStatus
from app.models.master_data import Ward
from app.models.transaction import BorrowTransaction, TransactionStatus
from app.models.user import ROLE_ADMINISTRATOR, Role, User
from app.schemas.sync import SyncReceiptBody
from app.schemas.transaction import BorrowRequest
from app.services import borrow_service, sync_service

# Conflict classes only an administrator may see or resolve (section 9.6:
# the FORBIDDEN class concerns user permissions).
ADMIN_ONLY_RESULT_CODES = ("FORBIDDEN",)

# Defined by the parallel "too old" PR; referenced by string here only.
OP_TOO_OLD_CODE = "OP_TOO_OLD"

LIST_STATUSES = ("unresolved", "conflict", "pending", "resolved")
MAX_LIMIT = 100
DEFAULT_LIMIT = 50


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cutoff(now: datetime) -> datetime:
    return now - sync_service.DEPENDENCY_WINDOW


async def is_administrator(db: AsyncSession, user_id: uuid.UUID) -> bool:
    name = (
        await db.execute(select(Role.name).join(User, User.role_id == Role.id).where(User.id == user_id))
    ).scalar_one_or_none()
    return name == ROLE_ADMINISTRATOR


def _admin_only(row: ClientOperation) -> bool:
    return row.result_code in ADMIN_ONLY_RESULT_CODES


def _uuid_or_none(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _body(row: ClientOperation) -> dict:
    body = (row.payload or {}).get(row.op_type)
    return body if isinstance(body, dict) else {}


# ---- visibility ----------------------------------------------------------

def _visible_clause(now: datetime, status: str, is_admin: bool):
    if status == "conflict":
        clause = ClientOperation.status == OP_STATUS_CONFLICT
    elif status == "pending":
        clause = and_(ClientOperation.status == OP_STATUS_PENDING, ClientOperation.first_seen_at <= _cutoff(now))
    elif status == "resolved":
        clause = ClientOperation.status == OP_STATUS_RESOLVED
    else:
        clause = reviewable_clause(_cutoff(now))
    if not is_admin:
        # `result_code IS NULL` must stay visible: NOT IN alone drops NULLs.
        clause = and_(
            clause,
            (ClientOperation.result_code.is_(None))
            | (ClientOperation.result_code.not_in(ADMIN_ONLY_RESULT_CODES)),
        )
    return clause


# ---- enrichment (batched; no N+1) ---------------------------------------

async def _enrich(db: AsyncSession, rows: list[ClientOperation]) -> dict[str, dict]:
    user_ids: set[uuid.UUID] = set()
    eq_ids: set[uuid.UUID] = set()
    ward_ids: set[uuid.UUID] = set()
    tx_ids: set[uuid.UUID] = set()
    for r in rows:
        user_ids.update(u for u in (r.user_id, r.submitted_by_user_id, r.resolved_by) if u)
        body = _body(r)
        if r.op_type == OP_TYPE_DISPATCH:
            if (e := _uuid_or_none(body.get("equipment_id"))):
                eq_ids.add(e)
            if (w := _uuid_or_none(body.get("ward_id"))):
                ward_ids.add(w)
        elif (t := _uuid_or_none(body.get("transaction_id"))):
            tx_ids.add(t)
    users = {}
    if user_ids:
        users = {
            u.id: u
            for u in (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars()
        }
    txs = {}
    if tx_ids:
        txs = {
            t.id: t
            for t in (await db.execute(select(BorrowTransaction).where(BorrowTransaction.id.in_(tx_ids)))).scalars()
        }
    eq_ids.update(t.equipment_id for t in txs.values())
    ward_ids.update(t.ward_id for t in txs.values() if t.ward_id)
    eqs = {}
    if eq_ids:
        eqs = {e.id: e for e in (await db.execute(select(Equipment).where(Equipment.id.in_(eq_ids)))).scalars()}
    wards = {}
    if ward_ids:
        wards = {w.id: w for w in (await db.execute(select(Ward).where(Ward.id.in_(ward_ids)))).scalars()}
    return {"users": users, "txs": txs, "eqs": eqs, "wards": wards}


def _user_ref(users: dict, uid: uuid.UUID | None):
    u = users.get(uid) if uid else None
    return {"id": u.id, "full_name": u.full_name} if u else None


def _item(row: ClientOperation, ctx: dict) -> dict:
    body = _body(row)
    eq = ward = None
    tx = None
    outcome = None
    if row.op_type == OP_TYPE_DISPATCH:
        eq = ctx["eqs"].get(_uuid_or_none(body.get("equipment_id")))
        ward = ctx["wards"].get(_uuid_or_none(body.get("ward_id")))
    else:
        tx = ctx["txs"].get(_uuid_or_none(body.get("transaction_id")))
        eq = ctx["eqs"].get(tx.equipment_id) if tx else None
        ward = ctx["wards"].get(tx.ward_id) if tx and tx.ward_id else None
        outcome = body.get("receipt_outcome")
    note = row.resolution_note if row.resolution == RESOLUTION_DISMISSED else None
    return {
        "op_id": row.op_id,
        "op_type": row.op_type,
        "status": row.status,
        "result_code": row.result_code,
        "admin_only": _admin_only(row),
        "stale_context": bool(row.stale_context),
        "time_flag": row.time_flag,
        "device_id": row.device_id,
        "received_at": row.received_at,
        "first_seen_at": row.first_seen_at,
        "occurred_at": row.occurred_at,
        "attempt_count": row.attempt_count,
        "operator": _user_ref(ctx["users"], row.user_id),
        "submitted_by": _user_ref(ctx["users"], row.submitted_by_user_id)
        if row.submitted_by_user_id and row.submitted_by_user_id != row.user_id
        else None,
        "equipment": {
            "id": eq.id,
            "bcm_code": eq.bcm_code,
            "equipment_name": eq.equipment_name,
            "status": eq.status.value,
        }
        if eq
        else None,
        "ward_name": ward.name if ward else None,
        "transaction_id": row.transaction_id or (tx.id if tx else None),
        "receipt_outcome": outcome,
        "resolution": row.resolution,
        "dismiss_reason": note.split(":", 1)[0] if note else None,
        "resolved_by": _user_ref(ctx["users"], row.resolved_by),
        "resolved_at": row.resolved_at,
    }


# ---- list / detail --------------------------------------------------------

async def list_items(
    db: AsyncSession,
    *,
    is_admin: bool,
    status: str = "unresolved",
    result_code: str | None = None,
    op_type: str | None = None,
    operator_id: uuid.UUID | None = None,
    stale_context: bool | None = None,
    device_id: uuid.UUID | None = None,
    received_from: datetime | None = None,
    received_to: datetime | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> dict:
    if status not in LIST_STATUSES:
        raise InvalidInputError(f"status must be one of: {', '.join(LIST_STATUSES)}.")
    if op_type is not None and op_type not in ("dispatch", "receipt"):
        raise InvalidInputError("op_type must be 'dispatch' or 'receipt'.")
    now = _now()
    conds = [_visible_clause(now, status, is_admin)]
    if result_code:
        conds.append(ClientOperation.result_code == result_code)
    if op_type:
        conds.append(ClientOperation.op_type == op_type)
    if operator_id:
        conds.append(ClientOperation.user_id == operator_id)
    if stale_context is not None:
        conds.append(ClientOperation.stale_context.is_(stale_context))
    if device_id:
        conds.append(ClientOperation.device_id == device_id)
    if received_from:
        conds.append(ClientOperation.received_at >= received_from)
    if received_to:
        conds.append(ClientOperation.received_at <= received_to)

    total = (await db.execute(select(func.count()).select_from(ClientOperation).where(*conds))).scalar_one()
    # Section 9.8: stale_context first; then oldest first (nothing expires,
    # so age order surfaces the longest-waiting item); op_id breaks ties.
    rows = (
        (
            await db.execute(
                select(ClientOperation)
                .where(*conds)
                .order_by(ClientOperation.stale_context.desc(), ClientOperation.received_at.asc(), ClientOperation.op_id)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    ctx = await _enrich(db, list(rows))
    return {"total": total, "limit": limit, "offset": offset, "items": [_item(r, ctx) for r in rows]}


async def _load_visible(db: AsyncSession, op_id: uuid.UUID, is_admin: bool, *, include_resolved: bool) -> ClientOperation:
    row = await client_op_crud.get(db, op_id)
    now = _now()
    open_ = (
        row is not None
        and (
            row.status == OP_STATUS_CONFLICT
            or (row.status == OP_STATUS_PENDING and _utc(row.first_seen_at) <= _cutoff(now))
        )
    )
    if row is None or not (open_ or (include_resolved and row.status == OP_STATUS_RESOLVED)):
        if row is None or not include_resolved:
            if row is None:
                raise ResourceNotFoundError("Review item not found")
            raise SyncOpNotResolvableError("This operation is not open for review.")
        raise ResourceNotFoundError("Review item not found")
    if _admin_only(row) and not is_admin:
        raise SyncReviewAdminOnlyError("This item can only be handled by an administrator.")
    return row


def _utc(v: datetime) -> datetime:
    return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)


async def _precondition(db: AsyncSession, row: ClientOperation) -> str | None:
    """Advisory: does the lifecycle precondition hold right now? Returns the
    blocking code or None. The real check is the service call itself."""
    body = _body(row)
    if row.op_type == OP_TYPE_DISPATCH:
        eq_id, ward_id = _uuid_or_none(body.get("equipment_id")), _uuid_or_none(body.get("ward_id"))
        eq = await db.get(Equipment, eq_id) if eq_id else None
        if eq is None:
            return "EQUIPMENT_NOT_FOUND"
        if eq.status != EquipmentStatus.AVAILABLE_AT_POOL:
            return "EQUIPMENT_NOT_AVAILABLE"
        if ward_id is None or await db.get(Ward, ward_id) is None:
            return "INVALID_INPUT"
        return None
    tx_id = _uuid_or_none(body.get("transaction_id"))
    tx = await transaction_crud.get_by_id(db, tx_id) if tx_id else None
    if tx is None:
        return "TRANSACTION_NOT_FOUND"
    if tx.status != TransactionStatus.OPEN:
        return "TRANSACTION_ALREADY_RETURNED"
    return None


async def _business_time(db: AsyncSession, row: ClientOperation, now: datetime) -> datetime:
    """Resolution time, except an ``OP_TOO_OLD`` op: the resolver confirms
    the stored (unclamped) ``occurred_at``. Relational guards still apply
    (a receipt never precedes its dispatch; a dispatch never precedes the
    equipment's latest receipt)."""
    if row.result_code != OP_TOO_OLD_CODE or row.occurred_at is None:
        return now
    t = _utc(row.occurred_at)
    body = _body(row)
    if row.op_type == OP_TYPE_DISPATCH:
        eq_id = _uuid_or_none(body.get("equipment_id"))
        last = await transaction_crud.latest_returned_at(db, eq_id) if eq_id else None
        if last is not None and _utc(last) > t:
            t = _utc(last)
    else:
        tx_id = _uuid_or_none(body.get("transaction_id"))
        tx = await transaction_crud.get_by_id(db, tx_id) if tx_id else None
        if tx is not None and _utc(tx.borrowed_at) > t:
            t = _utc(tx.borrowed_at)
    return min(t, now)


async def get_detail(db: AsyncSession, op_id: uuid.UUID, *, is_admin: bool) -> dict:
    row = await _load_visible(db, op_id, is_admin, include_resolved=True)
    ctx = await _enrich(db, [row])
    item = _item(row, ctx)
    body = _body(row)
    summary = (
        {"dispatch_type": body.get("dispatch_type"), "routine_round": body.get("routine_round"), "notes": body.get("notes")}
        if row.op_type == OP_TYPE_DISPATCH
        else {"transaction_id": body.get("transaction_id"), "receipt_outcome": body.get("receipt_outcome"), "notes": body.get("notes")}
    )
    blocker = None if row.status == OP_STATUS_RESOLVED else await _precondition(db, row)
    return {
        **item,
        "payload_summary": summary,
        "resolution_note": row.resolution_note,
        "apply_now_possible": row.status != OP_STATUS_RESOLVED and blocker is None,
        "apply_now_blocker": blocker,
    }


# ---- resolve --------------------------------------------------------------

async def dismiss(
    db: AsyncSession,
    op_id: uuid.UUID,
    resolver_id: uuid.UUID,
    *,
    is_admin: bool,
    reason: str,
    note: str | None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    row = await _load_visible(db, op_id, is_admin, include_resolved=False)
    now = _now()
    prior = {"status": row.status, "result_code": row.result_code}
    original_user, device_id = row.user_id, row.device_id
    text_note = f"{reason}: {note.strip()}" if note and note.strip() else reason
    won = (
        await db.execute(
            update(ClientOperation)
            .where(ClientOperation.op_id == op_id, reviewable_clause(_cutoff(now)))
            .values(
                status=OP_STATUS_RESOLVED,
                resolution=RESOLUTION_DISMISSED,
                resolved_by=resolver_id,
                resolved_at=now,
                resolution_note=text_note,
            )
        )
    ).rowcount == 1
    if not won:
        await db.rollback()
        raise SyncOpNotResolvableError("This item was already resolved by someone else.")
    await audit_crud.create(
        db,
        user_id=resolver_id,
        action=AUDIT_ACTION_SYNC_CONFLICT_RESOLVED,
        entity_type=AUDIT_ENTITY_CLIENT_OPERATION,
        entity_id=op_id,
        before_data=prior,
        after_data={
            "status": OP_STATUS_RESOLVED,
            "resolution": RESOLUTION_DISMISSED,
            "reason": reason,
            "resolver_user_id": str(resolver_id),
            "original_user_id": str(original_user),
            "device_id": str(device_id),
            "original_op_id": str(op_id),
            "new_op_id": None,
        },
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    return {"op_id": op_id, "status": OP_STATUS_RESOLVED, "resolution": RESOLUTION_DISMISSED, "resolved_by": resolver_id, "resolved_at": now}


async def apply_now(
    db: AsyncSession,
    op_id: uuid.UUID,
    resolver_id: uuid.UUID,
    *,
    is_admin: bool,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    row = await _load_visible(db, op_id, is_admin, include_resolved=False)
    now = _now()
    prior_status, prior_code = row.status, row.result_code
    operator_id, device_id, op_type = row.user_id, row.device_id, row.op_type
    payload = dict(row.payload)
    keep_code = _admin_only(row)
    business_time = await _business_time(db, row, now)

    try:
        if op_type == OP_TYPE_DISPATCH:
            body = BorrowRequest.model_validate(payload.get("dispatch") or {})
        else:
            body = SyncReceiptBody.model_validate(payload.get("receipt") or {})
    except Exception as exc:  # stored payload no longer valid for the schema
        raise InvalidInputError("The stored payload can no longer be applied.") from exc

    new_op_id = uuid.uuid4()
    link = ResolveLink(
        original_op_id=op_id,
        original_user_id=operator_id,
        original_device_id=device_id,
        resolver_user_id=resolver_id,
        pending_cutoff=_cutoff(now),
        resolved_at=now,
        prior_status=prior_status,
        prior_result_code=prior_code,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    ctx = ClientOpContext(
        op_id=new_op_id,
        # The (device_id, device_seq) pair must be unique; a resolver-originated
        # op has no device, so it gets its own synthetic one.
        device_id=uuid.uuid4(),
        device_seq=0,
        user_id=operator_id,
        submitted_by_user_id=resolver_id,
        op_type=op_type,
        payload_hash=sync_service.payload_hash(payload),
        payload=payload,
        occurred_at_local=now,
        clock_offset_ms=0,
        resolves=link,
    )
    try:
        if op_type == OP_TYPE_DISPATCH:
            tx = await borrow_service.borrow(
                db,
                equipment_id=body.equipment_id,
                borrower_user_id=operator_id,
                ward_id=body.ward_id,
                dispatch_type=body.dispatch_type,
                routine_round=body.routine_round,
                department_id=body.department_id,
                phone_number=body.phone_number,
                pickup_location_id=body.pickup_location_id,
                dropoff_location_id=body.dropoff_location_id,
                notes=body.notes,
                ip_address=ip_address,
                user_agent=user_agent,
                actor_user_id=resolver_id,
                client_op=ctx,
                borrowed_at=business_time,
            )
        else:
            tx = await borrow_service.return_equipment(
                db,
                transaction_id=body.transaction_id,
                receipt_outcome=body.receipt_outcome,
                notes=body.notes,
                received_by_user_id=operator_id,
                ip_address=ip_address,
                user_agent=user_agent,
                actor_user_id=resolver_id,
                client_op=ctx,
                returned_at=business_time,
            )
    except (ClientOpAlreadyProcessedError, ClientOpLedgerConflictError) as exc:
        # The service rolled back: another resolver (or the client's retry)
        # moved the row first. Nothing of ours was written.
        raise SyncOpNotResolvableError("This item was already resolved by someone else.") from exc
    except DomainError as exc:
        await db.rollback()
        if not isinstance(exc, sync_service._CONFLICT_ERRORS):
            raise
        return await _apply_failed(db, op_id, exc, resolver_id, keep_code)
    except Exception:
        await db.rollback()
        raise

    return {
        "op_id": op_id,
        "status": OP_STATUS_RESOLVED,
        "resolution": client_op_crud.RESOLUTION_APPLIED_AS,
        "resolved_by": resolver_id,
        "resolved_at": now,
        "new_op_id": new_op_id,
        "transaction_id": tx.id,
    }


async def _apply_failed(db: AsyncSession, op_id: uuid.UUID, exc: DomainError, resolver_id: uuid.UUID, keep_code: bool):
    """Apply now did not hold. The item stays in review with the fresh
    reason (unless someone else resolved it meanwhile: then 409)."""
    now = _now()
    values = {"resolution_note": f"apply_failed:{exc.code}"}
    if not keep_code:
        values["result_code"] = exc.code
    won = (
        await db.execute(
            update(ClientOperation)
            .where(ClientOperation.op_id == op_id, reviewable_clause(_cutoff(now)))
            .values(**values)
        )
    ).rowcount == 1
    if not won:
        await db.rollback()
        raise SyncOpNotResolvableError("This item was already resolved by someone else.") from exc
    await db.commit()
    raise SyncApplyFailedError(f"Apply now failed ({exc.code}): {exc.message}. The item stays in review.") from exc
