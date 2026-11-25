"""Roadmap PR29 (D1): the audited HN reveal.

The sole code path that returns a plaintext HN. The audit row (who/when/which
transaction) is flushed in the same database transaction as the read and is
committed before the value is handed back, so a reveal can never happen
without its audit row; the row never contains the value.
"""
import uuid

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import hn_crypto
from app.core.audit import AUDIT_ACTION_HN_REVEAL, AUDIT_ENTITY_BORROW_TRANSACTION, record_audit_event
from app.core.exceptions import HnNotRecordedError, TransactionNotFoundError
from app.models.transaction import BorrowTransaction


async def reveal_hn(
    db: AsyncSession, *, transaction_id: uuid.UUID, actor_user_id: uuid.UUID, request: Request | None
) -> str:
    row = (
        await db.execute(
            select(BorrowTransaction.id, BorrowTransaction.has_hn, BorrowTransaction.hn_ciphertext).where(
                BorrowTransaction.id == transaction_id
            )
        )
    ).one_or_none()
    if row is None:
        raise TransactionNotFoundError("Transaction not found")
    if not row.has_hn or not row.hn_ciphertext:
        raise HnNotRecordedError("No HN is recorded for this transaction")
    # Raises HnUnavailableError (503) without an audit row when the key is
    # missing or wrong: nothing was revealed.
    hn = hn_crypto.decrypt_hn(row.hn_ciphertext)
    await record_audit_event(
        db,
        actor_user_id=actor_user_id,
        action=AUDIT_ACTION_HN_REVEAL,
        entity_type=AUDIT_ENTITY_BORROW_TRANSACTION,
        entity_id=transaction_id,
        after={"transaction_id": str(transaction_id)},
        request=request,
    )
    await db.commit()
    return hn
