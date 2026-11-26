"""Roadmap PR29 (D1): the audited HN reveal.

The sole code path that returns a plaintext HN. The audit row (who/when/which
transaction) is flushed in the same database transaction as the read and is
committed before the value is handed back, so a reveal can never happen
without its audit row; the row never contains the value.
"""
import uuid
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import hn_crypto
from app.core.audit import AUDIT_ACTION_HN_ADD, AUDIT_ACTION_HN_REVEAL, AUDIT_ENTITY_BORROW_TRANSACTION, record_audit_event
from app.core.exceptions import (
    HnAlreadyRecordedError,
    HnNotRecordedError,
    TransactionNotFoundError,
    TransactionNotOpenError,
)
from app.crud import transaction as transaction_crud
from app.models.transaction import BorrowTransaction, TransactionStatus


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


async def add_hn(
    db: AsyncSession, *, transaction_id: uuid.UUID, hn: str, actor_user_id: uuid.UUID, request: Request | None
) -> BorrowTransaction:
    """Roadmap PR34 (D15): add an HN to an existing OPEN dispatch that has none
    (Standby -> in use). Never replaces an existing HN (409). The write is a
    single conditional UPDATE so two concurrent adds cannot both win, and the
    audit row (actor/transaction, never the value) is committed with it.
    """
    row = (
        await db.execute(
            select(BorrowTransaction.id, BorrowTransaction.status, BorrowTransaction.has_hn).where(
                BorrowTransaction.id == transaction_id
            )
        )
    ).one_or_none()
    if row is None:
        raise TransactionNotFoundError("Transaction not found")
    if row.status != TransactionStatus.OPEN:
        raise TransactionNotOpenError("HN can only be added to an open dispatch")
    if row.has_hn:
        raise HnAlreadyRecordedError("This dispatch already has an HN; it cannot be replaced")
    # Raises HnUnavailableError (503) when the key is missing: nothing written.
    ciphertext = hn_crypto.encrypt_hn(hn)
    result = await db.execute(
        update(BorrowTransaction)
        .where(
            BorrowTransaction.id == transaction_id,
            BorrowTransaction.status == TransactionStatus.OPEN,
            BorrowTransaction.has_hn.is_(False),
        )
        .values(hn_ciphertext=ciphertext, has_hn=True, hn_added_at=datetime.now(timezone.utc))
    )
    if result.rowcount != 1:  # lost a race (received or HN added concurrently)
        await db.rollback()
        raise HnAlreadyRecordedError("This dispatch was changed by someone else; reload and retry")
    await record_audit_event(
        db,
        actor_user_id=actor_user_id,
        action=AUDIT_ACTION_HN_ADD,
        entity_type=AUDIT_ENTITY_BORROW_TRANSACTION,
        entity_id=transaction_id,
        after={"transaction_id": str(transaction_id), "has_hn": True},  # never the value
        request=request,
    )
    await db.commit()
    db.expire_all()
    return await transaction_crud.get_by_id(db, transaction_id)
