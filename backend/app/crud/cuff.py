"""Roadmap PR28 (D11): persistence for ``transaction_cuffs`` (cuff balances).

Only the conditional UPDATE in ``apply_return`` may raise ``returned_count``;
it is the concurrency guard (two concurrent returns cannot together exceed
what was issued) and the DB CHECK constraint is the backstop.
"""
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cuff import TransactionCuff
from app.models.equipment import Equipment
from app.models.master_data import Ward
from app.models.transaction import BorrowTransaction
from app.schemas.checklist import CUFF_TYPES, CuffCounts


async def create_issued(db: AsyncSession, *, transaction_id: uuid.UUID, counts: CuffCounts) -> None:
    for cuff_type, n in counts.as_dict().items():
        if n > 0:
            db.add(TransactionCuff(transaction_id=transaction_id, cuff_type=cuff_type, issued_count=n, returned_count=0))
    await db.flush()


async def balances_for_transactions(
    db: AsyncSession, transaction_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, tuple[int, int]]]:
    """transaction id -> cuff type -> (issued, returned). Transactions that
    never issued cuffs are absent."""
    out: dict[uuid.UUID, dict[str, tuple[int, int]]] = {}
    if not transaction_ids:
        return out
    rows = (
        await db.execute(select(TransactionCuff).where(TransactionCuff.transaction_id.in_(transaction_ids)))
    ).scalars().all()
    for r in rows:
        out.setdefault(r.transaction_id, {})[r.cuff_type] = (r.issued_count, r.returned_count)
    return out


def outstanding_counts(balance: dict[str, tuple[int, int]] | None) -> CuffCounts:
    balance = balance or {}
    return CuffCounts(**{t: balance.get(t, (0, 0))[0] - balance.get(t, (0, 0))[1] for t in CUFF_TYPES})


def issued_counts(balance: dict[str, tuple[int, int]] | None) -> CuffCounts:
    balance = balance or {}
    return CuffCounts(**{t: balance.get(t, (0, 0))[0] for t in CUFF_TYPES})


async def apply_return(db: AsyncSession, *, transaction_id: uuid.UUID, cuff_type: str, count: int) -> bool:
    """Raise ``returned_count`` by ``count`` only if that keeps it within
    ``issued_count``. True = applied."""
    result = await db.execute(
        update(TransactionCuff)
        .where(
            TransactionCuff.transaction_id == transaction_id,
            TransactionCuff.cuff_type == cuff_type,
            TransactionCuff.returned_count + count <= TransactionCuff.issued_count,
        )
        .values(returned_count=TransactionCuff.returned_count + count)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


async def list_outstanding(db: AsyncSession, *, ward_id: uuid.UUID | None = None):
    """Rows (TransactionCuff, BorrowTransaction, Equipment, ward name) with
    issued > returned, oldest dispatch first."""
    stmt = (
        select(TransactionCuff, BorrowTransaction, Equipment, Ward.name)
        .join(BorrowTransaction, BorrowTransaction.id == TransactionCuff.transaction_id)
        .join(Equipment, Equipment.id == BorrowTransaction.equipment_id)
        .outerjoin(Ward, Ward.id == BorrowTransaction.ward_id)
        .where(TransactionCuff.issued_count > TransactionCuff.returned_count)
        .order_by(BorrowTransaction.borrowed_at, BorrowTransaction.id, TransactionCuff.cuff_type)
    )
    if ward_id is not None:
        stmt = stmt.where(BorrowTransaction.ward_id == ward_id)
    return (await db.execute(stmt)).all()
