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
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.equipment import Equipment
from app.models.export import (
    EVENT_TYPE_DISPATCH,
    EVENT_TYPE_RECEIPT,
    ExportApiKey,
    ExportEvent,
    ExportEventCounter,
)
from app.models.master_data import EquipmentCategory, Ward
from app.models.transaction import BorrowTransaction
from app.models.user import User

MAX_PAGE_SIZE = 500
DEFAULT_PAGE_SIZE = 100
KEY_PREFIX = "mepx_"
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
    db: AsyncSession, *, transaction_id: uuid.UUID, event_type: str, event_at: datetime
) -> ExportEvent:
    """Append one event. Must be the last write before the caller commits and
    must run in the same database transaction as the business change, so the
    event exists if and only if the dispatch/receipt does."""
    seq = await _next_seq(db)
    event = ExportEvent(
        seq=seq,
        event_id=uuid.uuid4(),
        event_type=event_type,
        transaction_id=transaction_id,
        event_at=event_at,
    )
    db.add(event)
    await db.flush()
    return event


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


async def query_events(db: AsyncSession, *, after: int, limit: int) -> tuple[list[dict], bool]:
    """Events with seq > after, ascending, at most ``limit``. Returns
    (events, has_more)."""
    dispatcher = aliased(User)
    receiver = aliased(User)
    stmt = (
        select(ExportEvent, BorrowTransaction, Equipment, EquipmentCategory.name, Ward, dispatcher.full_name, receiver.full_name)
        .join(BorrowTransaction, BorrowTransaction.id == ExportEvent.transaction_id)
        .join(Equipment, Equipment.id == BorrowTransaction.equipment_id)
        .outerjoin(EquipmentCategory, EquipmentCategory.id == Equipment.category_id)
        .outerjoin(Ward, Ward.id == BorrowTransaction.ward_id)
        .outerjoin(dispatcher, dispatcher.id == BorrowTransaction.borrower_user_id)
        .outerjoin(receiver, receiver.id == BorrowTransaction.received_by_user_id)
        .where(ExportEvent.seq > after)
        .order_by(ExportEvent.seq)
        .limit(limit + 1)
    )
    rows = (await db.execute(stmt)).all()
    has_more = len(rows) > limit
    return [_serialize(*row) for row in rows[:limit]], has_more


def _serialize(event, tx, equipment, category_name, ward, dispatcher_name, receiver_name) -> dict:
    """Explicit allow-list. Item No, asset number, serial number, notes, phone
    and borrower_name are deliberately absent (api-information-boundaries.md;
    free-text fields could carry anything an operator typed)."""
    is_receipt = event.event_type == EVENT_TYPE_RECEIPT
    outcome = tx.receipt_outcome if is_receipt else None
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
        "operator_name": receiver_name if is_receipt else dispatcher_name,
    }


# ---------------------------------------------------------------------------
# Machine keys
# ---------------------------------------------------------------------------


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


async def create_key(db: AsyncSession, *, name: str, created_by: uuid.UUID) -> tuple[ExportApiKey, str]:
    """Returns (row, plaintext key). The plaintext is shown once and never
    stored."""
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    row = ExportApiKey(name=name, key_hash=hash_key(key), key_prefix=key[:12], created_by_user_id=created_by)
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
