"""D31: erase patient HN ciphertext 2 years after ``borrowed_at``.

Clears ``hn_ciphertext`` (open dispatches too), keeps ``hn_recorded``. One
count-only audit entry per applying run; no export event, no ``hn_update``.
Idempotent (only non-null ciphertext rows match). Never logs values.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AUDIT_ACTION_HN_ERASE, AUDIT_ENTITY_BORROW_TRANSACTION
from app.crud import audit as audit_crud
from app.models.transaction import BorrowTransaction

logger = logging.getLogger(__name__)
RETENTION_DAYS = 730  # 2 years


async def erase_old_hn(db: AsyncSession, *, apply: bool, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=RETENTION_DAYS)
    cond = (BorrowTransaction.hn_ciphertext.is_not(None), BorrowTransaction.borrowed_at < cutoff)
    if not apply:
        return (await db.execute(select(func.count()).select_from(BorrowTransaction).where(*cond))).scalar_one()
    result = await db.execute(update(BorrowTransaction).where(*cond).values(hn_ciphertext=None))
    count = result.rowcount or 0
    await audit_crud.create(
        db, user_id=None, action=AUDIT_ACTION_HN_ERASE, entity_type=AUDIT_ENTITY_BORROW_TRANSACTION,
        entity_id=None, after_data={"erased_count": count},
    )
    await db.commit()
    logger.info("HN retention erase: %d erased", count)
    return count
