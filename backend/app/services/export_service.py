"""Roadmap PR25B -- read-only export API: outbox, cursor, and machine keys.

Why the cursor cannot skip a committed event
--------------------------------------------
Paging by timestamp (or by an ordinary sequence/IDENTITY value) is unsafe in
PostgreSQL because *assignment order is not commit order*: a transaction can
take timestamp/sequence value 10, stall, and commit after a transaction that
took 11 has committed and been polled. The consumer, having seen 11, advances
past 10 and never receives it.

This module closes that hole by construction rather than with a lag window.
``seq`` is assigned by ``record_event`` as::

    UPDATE export_event_counter SET last_seq = last_seq + 1 WHERE id = 1
    RETURNING last_seq

and it is the *last* write before the business transaction commits. The
UPDATE takes a row lock that PostgreSQL holds until the writing transaction
commits or rolls back. Consequences:

1. Writers are serialized on that one row, so seq N+1 is only ever assigned
   after the transaction holding seq N has finished. A rollback also rolls the
   counter back, so there are no gaps either.
2. PostgreSQL marks a transaction committed in the shared snapshot state
   *before* releasing its locks, so by the time seq N+1's transaction can
   exist, seq N is already visible to every snapshot that can see N+1.
3. Therefore the set of visible ``export_events`` rows is always a gap-free
   prefix ``1..K``. A reader that has consumed up to ``after`` and asks for
   ``seq > after ORDER BY seq`` can never be handed row K+2 while K+1 is still
   invisible, because K+2 cannot exist before K+1 has committed.

The cost is that dispatch/receipt commits queue behind one another for the
few milliseconds between taking the counter and committing. That is
irrelevant at hospital-pool volumes (tens of events per hour), and the counter
is always the last lock taken in a request, so it cannot take part in a lock
cycle with the equipment/transaction rows.

The read side is a single ``SELECT`` (one snapshot), so it needs no lag window
either. The ``after`` cursor is the ``seq`` of the last event the consumer
processed; delivery is at-least-once and the consumer dedupes on ``event_id``.
"""
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core import hn_crypto
from app.core.config import settings
from app.models.client_operation import OP_STATUS_APPLIED, OP_TYPE_DISPATCH, ClientOperation
from app.models.equipment import EQUIPMENT_SOURCE_POOL, Equipment
from app.models.export import (
    EVENT_TYPE_DISPATCH,
    EVENT_TYPE_HN_UPDATE,
    EVENT_TYPE_RECEIPT,
    ExportApiKey,
    ExportEvent,
    ExportEventCounter,
)
from app.models.master_data import EquipmentCategory, Ward
from app.models.transaction import BorrowTransaction, TransactionStatus
from app.models.user import User
from app.services.system_notes import clean_label

MAX_PAGE_SIZE = 500
DEFAULT_PAGE_SIZE = 100
KEY_PREFIX = "mepx_"
# Fixed device id the legacy sheet sync stamps on its client_operations
# (app.services.legacy_sheet_sync.runner.DEVICE_ID; a test pins the two equal,
# so this module need not import the sync's Google client stack).
LEGACY_SYNC_DEVICE_ID = uuid.UUID("a6c1f2d4-5b3e-4c7a-9d10-6e2f8b4a1c35")
# last_used_at is informational; throttle its write so a 30 s poller does not
# turn every read into a write.
_LAST_USED_GRANULARITY = timedelta(minutes=5)


# ---------------------------------------------------------------------------
# Writing the outbox (called from borrow_service, inside the caller's txn)
# ---------------------------------------------------------------------------


async def _next_seq(db: AsyncSession) -> int:
    stmt = (
        update(ExportEventCounter)
        .where(ExportEventCounter.id == 1)
        .values(last_seq=ExportEventCounter.last_seq + 1)
        .returning(ExportEventCounter.last_seq)
    )
    seq = (await db.execute(stmt)).scalar_one_or_none()
    if seq is not None:
        return seq
    # No counter row yet (fresh SQLite test DB; production gets it from the
    # migration). Create it in a savepoint so a concurrent creator is not
    # fatal, then retry the locking UPDATE.
    try:
        async with db.begin_nested():
            await db.execute(insert(ExportEventCounter).values(id=1, last_seq=0))
    except IntegrityError:
        pass
    return (await db.execute(stmt)).scalar_one()


async def record_event(
    db: AsyncSession,
    *,
    transaction_id: uuid.UUID,
    event_type: str,
    event_at: datetime,
    correction: bool = False,
    corrects_event_id: uuid.UUID | None = None,
) -> ExportEvent | None:
    """Append one event. Must be the last write before the caller commits and
    must run in the same database transaction as the business change, so the
    event exists if and only if the dispatch/receipt does.

    Roadmap PR33 (D14): demo/loan equipment is EXCLUDED from this API -- no
    event is recorded (returns None) and so no seq is consumed. The source
    is checked before the counter row lock is taken."""
    source = (
        await db.execute(
            select(Equipment.equipment_source)
            .join(BorrowTransaction, BorrowTransaction.equipment_id == Equipment.id)
            .where(BorrowTransaction.id == transaction_id)
        )
    ).scalar_one_or_none()
    if source != EQUIPMENT_SOURCE_POOL:  # demo/loan, or the equipment lookup found nothing
        return None
    seq = await _next_seq(db)
    event = ExportEvent(
        seq=seq,
        event_id=uuid.uuid4(),
        event_type=event_type,
        transaction_id=transaction_id,
        event_at=event_at,
        correction=correction,
        corrects_event_id=corrects_event_id,
        # D28 hold-back runs from the server insert time, not the (possibly
        # backdated, offline) occurred time.
        created_at=datetime.now(timezone.utc),
    )
    db.add(event)
    await db.flush()
    return event


async def record_void(db: AsyncSession, *, tx: BorrowTransaction, voided_kind: str) -> None:
    """D28: called from the void/change-device/switch-action service after the
    event ``voided_kind`` ("dispatch" or "receipt") of ``tx`` was voided, in the
    caller's transaction.

    * original still inside its hold-back window (never visible): mark it
      ``withdrawn`` so it is never exposed and emit NOTHING;
    * original already visible: emit ONE compensating event (voided dispatch ->
      correction ``receipt``; voided receipt -> correction ``dispatch``), no HN.

    No hold-back on the correction: a void is not undoable, so there is no
    window to protect, and the external tool must re-key promptly. Demo/loan
    equipment has no original event, so nothing happens."""
    original_type = EVENT_TYPE_DISPATCH if voided_kind == "dispatch" else EVENT_TYPE_RECEIPT
    corrected = select(ExportEvent.corrects_event_id).where(ExportEvent.corrects_event_id.is_not(None))
    original = (
        await db.execute(
            select(ExportEvent)
            .where(
                ExportEvent.transaction_id == tx.id,
                ExportEvent.event_type == original_type,
                ExportEvent.correction.is_(False),
                ExportEvent.withdrawn.is_(False),
                ExportEvent.event_id.not_in(corrected),
            )
            .order_by(ExportEvent.seq.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if original is None:
        return
    now = datetime.now(timezone.utc)
    if not _visible(original, now):
        original.withdrawn = True
        await db.flush()
        if voided_kind == "dispatch":
            # An hn_update for the voided dispatch must not leak either.
            await db.execute(
                update(ExportEvent)
                .where(ExportEvent.transaction_id == tx.id, ExportEvent.event_type == EVENT_TYPE_HN_UPDATE)
                .values(withdrawn=True)
            )
        return
    await record_event(
        db,
        transaction_id=tx.id,
        event_type=EVENT_TYPE_RECEIPT if voided_kind == "dispatch" else EVENT_TYPE_DISPATCH,
        event_at=now,
        correction=True,
        corrects_event_id=original.event_id,
    )


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


async def head_seq(db: AsyncSession) -> int:
    return (await db.execute(select(func.coalesce(func.max(ExportEvent.seq), 0)))).scalar_one()


async def cursor_for_time(db: AsyncSession, at: datetime) -> int:
    """Cursor from which a consumer receives every event at or after ``at``:
    one less than the lowest seq whose event_time is >= ``at``. May re-deliver
    an event or two just before ``at`` if clocks interleave; never skips one."""
    first = (await db.execute(select(func.min(ExportEvent.seq)).where(ExportEvent.event_at >= at))).scalar_one()
    if first is None:
        return await head_seq(db)
    return first - 1


@dataclass
class EventsPage:
    events: list[dict]
    next_cursor: int
    has_more: bool
    hn_count: int = 0


def hold_seconds(event_type: str) -> int:
    """D28 undo window per event type. hn_update is not undoable: no hold."""
    if event_type == EVENT_TYPE_DISPATCH:
        return settings.EXPORT_HOLD_DISPATCH_SECONDS
    if event_type == EVENT_TYPE_RECEIPT:
        return settings.EXPORT_HOLD_RECEIPT_SECONDS
    return 0


def _visible(event: ExportEvent, now: datetime) -> bool:
    if event.correction:
        return True  # D28: compensating events need no hold-back (not undoable)
    created = event.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return now >= created + timedelta(seconds=hold_seconds(event.event_type))


async def _legacy_sets(db: AsyncSession, tx_ids: list[uuid.UUID]) -> tuple[set, set]:
    """Transactions whose dispatch / receipt was created by the legacy sheet
    sync: its applied ``client_operations`` rows carry the sync's fixed
    device id (the dispatch op id is the transaction id; a receipt op points
    at its transaction via ``transaction_id``)."""
    if not tx_ids:
        return set(), set()
    rows = (
        await db.execute(
            select(ClientOperation.op_id, ClientOperation.transaction_id, ClientOperation.op_type).where(
                ClientOperation.device_id == LEGACY_SYNC_DEVICE_ID,
                ClientOperation.status == OP_STATUS_APPLIED,
                or_(ClientOperation.op_id.in_(tx_ids), ClientOperation.transaction_id.in_(tx_ids)),
            )
        )
    ).all()
    dispatch, receipt = set(), set()
    for op_id, tx_id, op_type in rows:
        if op_type == OP_TYPE_DISPATCH:
            dispatch.add(op_id)
        elif tx_id is not None:
            receipt.add(tx_id)
    return dispatch, receipt


async def query_events(
    db: AsyncSession,
    *,
    after: int,
    limit: int,
    hn_allowed: bool = False,
    now: datetime | None = None,
) -> EventsPage:
    """Visible events with seq > after, ascending, at most ``limit``.

    Paging invariant (D28 hold-back + D29 hn_update): ``seq`` is gap-free and
    commit-ordered, but hold-back makes *visibility* non-monotonic (a receipt
    becomes visible after 30 s, an earlier dispatch only after 120 s). The scan
    therefore walks rows in seq order and STOPS at the first row that is not
    yet visible; nothing after it is returned even if it is already past its
    own window. ``next_cursor`` is the last row consumed (returned OR skipped
    as invisible-to-this-key), never past the blocking row, so no event is
    ever skipped. When blocked, ``has_more`` is False: there is nothing more
    to fetch *now*, and the consumer should wait and poll again.
    """
    now = now or datetime.now(timezone.utc)
    dispatcher = aliased(User)
    receiver = aliased(User)
    cols = [ExportEvent, BorrowTransaction, Equipment, EquipmentCategory.name, Ward, dispatcher.full_name, receiver.full_name]
    if hn_allowed:
        cols.append(BorrowTransaction.hn_ciphertext)  # deferred column: loaded only when HN may be returned
    base = (
        select(*cols)
        .join(BorrowTransaction, BorrowTransaction.id == ExportEvent.transaction_id)
        .join(Equipment, Equipment.id == BorrowTransaction.equipment_id)
        .outerjoin(EquipmentCategory, EquipmentCategory.id == Equipment.category_id)
        .outerjoin(Ward, Ward.id == BorrowTransaction.ward_id)
        .outerjoin(dispatcher, dispatcher.id == BorrowTransaction.borrower_user_id)
        .outerjoin(receiver, receiver.id == BorrowTransaction.received_by_user_id)
        .where(Equipment.equipment_source == EQUIPMENT_SOURCE_POOL, ExportEvent.withdrawn.is_(False))
        .order_by(ExportEvent.seq)
    )
    picked: list[tuple] = []
    cursor = after
    has_more = False
    blocked = False
    while not blocked and not has_more:
        rows = (await db.execute(base.where(ExportEvent.seq > cursor).limit(limit + 1))).all()
        if not rows:
            break
        for row in rows:
            event = row[0]
            if not _visible(event, now):
                blocked = True
                break
            if event.event_type == EVENT_TYPE_HN_UPDATE and not hn_allowed:
                cursor = event.seq  # consumed (skipped) without breaking the cursor
                continue
            if len(picked) == limit:
                has_more = True
                break
            picked.append(row)
            cursor = event.seq
        else:
            if len(rows) <= limit:
                break  # exhausted
            continue
    legacy_dispatch, legacy_receipt = await _legacy_sets(db, [r[1].id for r in picked])
    events, hn_count = [], 0
    for row in picked:
        item = _serialize(*row[:7], legacy_dispatch=legacy_dispatch, legacy_receipt=legacy_receipt)
        if (
            hn_allowed
            and not row[0].correction
            and row[1].status != TransactionStatus.VOIDED
            and item["event_type"] != EVENT_TYPE_RECEIPT
            and row[1].has_hn
            and row[7]
        ):
            item["hn"] = hn_crypto.decrypt_hn(row[7])  # HnUnavailableError -> 503, nothing returned
            hn_count += 1
        events.append(item)
    return EventsPage(events=events, next_cursor=cursor, has_more=has_more, hn_count=hn_count)


def _serialize(event, tx, equipment, category_name, ward, dispatcher_name, receiver_name, *, legacy_dispatch=(), legacy_receipt=()) -> dict:
    """Explicit allow-list. Item No, asset number, serial number, notes, phone
    and borrower_name are deliberately absent (api-information-boundaries.md;
    free-text fields could carry anything an operator typed). ``hn`` is added
    by the caller only under the D29 conditions."""
    is_receipt = event.event_type == EVENT_TYPE_RECEIPT
    if event.correction:
        # Voided side: the operator/contact of whichever side was recorded.
        dispatcher_name = receiver_name = dispatcher_name or receiver_name
    outcome = tx.receipt_outcome if is_receipt and not event.correction else None
    legacy = not event.correction and tx.id in (legacy_receipt if is_receipt else legacy_dispatch)
    operator = receiver_name if is_receipt else dispatcher_name
    keyer = clean_label(tx.receipt_keyer_label if is_receipt else tx.dispatch_keyer_label) or operator
    return {
        "seq": event.seq,
        "event_id": str(event.event_id),
        "event_type": event.event_type,
        "event_time": event.event_at,
        "transaction_id": str(tx.id),
        "transaction_no": tx.transaction_no,
        "equipment": {
            "id": str(equipment.id),
            "bcm_code": equipment.bcm_code,
            "name": equipment.equipment_name,
            "category": category_name,
        },
        "ward": {"id": str(ward.id), "code": ward.code, "name": ward.name} if ward else None,
        "dispatch_type": tx.dispatch_type.value if tx.dispatch_type else None,
        "routine_round": tx.routine_round.value if tx.routine_round else None,
        "receipt_outcome": outcome.value if outcome else None,
        "operator_name": operator,
        "origin": "legacy_sheet" if legacy else "app",
        "keyer_label": keyer,
        "contact_name": (tx.receipt_contact_name if is_receipt and not event.correction else tx.dispatch_contact_name),
        "transaction_status": tx.status.value if hasattr(tx.status, "value") else tx.status,
        "correction": bool(event.correction),
        "corrects_event_id": str(event.corrects_event_id) if event.corrects_event_id else None,
    }


# ---------------------------------------------------------------------------
# Machine keys
# ---------------------------------------------------------------------------


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


async def create_key(
    db: AsyncSession, *, name: str, created_by: uuid.UUID, scope_hn: bool = False
) -> tuple[ExportApiKey, str]:
    """Returns (row, plaintext key). The plaintext is shown once and never
    stored."""
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    row = ExportApiKey(name=name, key_hash=hash_key(key), key_prefix=key[:12], created_by_user_id=created_by, scope_hn=scope_hn)
    db.add(row)
    await db.flush()
    return row, key


async def list_keys(db: AsyncSession) -> list[ExportApiKey]:
    return list((await db.execute(select(ExportApiKey).order_by(ExportApiKey.created_at, ExportApiKey.id))).scalars())


async def authenticate_key(db: AsyncSession, presented: str) -> ExportApiKey | None:
    if not presented.startswith(KEY_PREFIX) or len(presented) > 200:
        return None
    digest = hash_key(presented)
    row = (await db.execute(select(ExportApiKey).where(ExportApiKey.key_hash == digest))).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    if not hmac.compare_digest(row.key_hash, digest):
        return None
    now = datetime.now(timezone.utc)
    if row.last_used_at is None or now - row.last_used_at > _LAST_USED_GRANULARITY:
        row.last_used_at = now
        await db.commit()
    return row
