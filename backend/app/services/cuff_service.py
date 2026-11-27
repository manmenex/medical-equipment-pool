"""Roadmap PR28 (D11): cuff accounting on top of ``transaction_cuffs``.

Cuffs are accessories attributed to the dispatch transaction (and therefore its
ward); they never change equipment state. Every movement writes an audit row.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    CuffReceiveNotAllowedError,
    CuffReturnExceedsOutstandingError,
    InvalidInputError,
    TransactionNotFoundError,
)
from app.crud import audit as audit_crud
from app.crud import cuff as cuff_crud
from app.crud import transaction as transaction_crud
from app.models.transaction import TransactionStatus
from app.schemas.checklist import CuffCounts, CryoCuffChecks, StandardChecks

AUDIT_ACTION_CUFF_ISSUE = "cuff_issue"
AUDIT_ACTION_CUFF_RETURN = "cuff_return"


def resolve_returned(
    receipt_checks: StandardChecks | CryoCuffChecks | None, cuffs_returned: CuffCounts | None
) -> CuffCounts:
    """Cuffs handed back at device receipt: explicit ``cuffs_returned`` wins,
    else a cryo_cuff checklist's ``cuffs``, else none (device-only receipt)."""
    if cuffs_returned is not None:
        return cuffs_returned
    if isinstance(receipt_checks, CryoCuffChecks):
        return receipt_checks.cuffs
    return CuffCounts()


async def validate_returnable(db: AsyncSession, transaction_id: uuid.UUID, counts: CuffCounts) -> None:
    """Read-only check that no type would exceed what is outstanding."""
    balances = await cuff_crud.balances_for_transactions(db, [transaction_id])
    outstanding = cuff_crud.outstanding_counts(balances.get(transaction_id)).as_dict()
    over = {t: {"requested": n, "outstanding": outstanding[t]} for t, n in counts.as_dict().items() if n > outstanding[t]}
    if over:
        raise CuffReturnExceedsOutstandingError(
            "Cannot receive more cuffs than are outstanding for this transaction.",
            details={"transaction_id": str(transaction_id), "exceeded": over},
        )


async def apply_return(db: AsyncSession, transaction_id: uuid.UUID, counts: CuffCounts) -> None:
    """Conditionally raise returned counts. Raises (caller rolls back) if a
    concurrent movement made any type exceed outstanding."""
    for cuff_type, n in counts.as_dict().items():
        if n > 0 and not await cuff_crud.apply_return(db, transaction_id=transaction_id, cuff_type=cuff_type, count=n):
            raise CuffReturnExceedsOutstandingError(
                "Cannot receive more cuffs than are outstanding for this transaction.",
                details={"transaction_id": str(transaction_id), "cuff_type": cuff_type},
            )


async def audit_issue(
    db: AsyncSession, *, actor_user_id, transaction_id, counts: CuffCounts, ip_address, user_agent
) -> None:
    await audit_crud.create(
        db,
        user_id=actor_user_id,
        action=AUDIT_ACTION_CUFF_ISSUE,
        entity_type="borrow_transaction",
        entity_id=transaction_id,
        after_data={"cuffs_issued": counts.as_dict()},
        ip_address=ip_address,
        user_agent=user_agent,
    )


async def audit_return(
    db: AsyncSession,
    *,
    actor_user_id,
    transaction_id,
    counts: CuffCounts,
    source: str,
    ward_contact_name: str | None,
    ip_address,
    user_agent,
) -> None:
    after = {"cuffs_returned": counts.as_dict(), "source": source}
    if ward_contact_name:
        after["ward_contact_name"] = ward_contact_name
    await audit_crud.create(
        db,
        user_id=actor_user_id,
        action=AUDIT_ACTION_CUFF_RETURN,
        entity_type="borrow_transaction",
        entity_id=transaction_id,
        after_data=after,
        ip_address=ip_address,
        user_agent=user_agent,
    )


async def receive_cuffs(
    db: AsyncSession,
    *,
    transaction_id: uuid.UUID,
    counts: CuffCounts,
    ward_contact_name: str | None,
    actor_user_id: uuid.UUID,
    ip_address: str | None,
    user_agent: str | None,
) -> dict:
    """``POST /transactions/{id}/receive-cuffs``: receive cuffs after the
    device was received (or the transaction was closed by re-dispatch).
    All-or-nothing across types; never exceeds outstanding."""
    tx = await transaction_crud.get_by_id(db, transaction_id)
    if tx is None:
        raise TransactionNotFoundError("Transaction not found")
    if counts.total() == 0:
        raise InvalidInputError("At least one cuff must be received.")
    if tx.status != TransactionStatus.CLOSED:
        raise CuffReceiveNotAllowedError(
            "Cuffs can be received separately only after the device has been received. "
            "Record them with the device receipt instead."
        )
    tx_id, tx_no = tx.id, tx.transaction_no
    await validate_returnable(db, tx_id, counts)
    try:
        await apply_return(db, tx_id, counts)
    except CuffReturnExceedsOutstandingError:
        await db.rollback()
        raise
    await audit_return(
        db,
        actor_user_id=actor_user_id,
        transaction_id=tx_id,
        counts=counts,
        source="receive_cuffs",
        ward_contact_name=ward_contact_name,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    return await summary(db, tx_id, tx_no)


async def summary(db: AsyncSession, transaction_id: uuid.UUID, transaction_no: str) -> dict:
    balance = (await cuff_crud.balances_for_transactions(db, [transaction_id])).get(transaction_id)
    issued = cuff_crud.issued_counts(balance)
    outstanding = cuff_crud.outstanding_counts(balance)
    returned = CuffCounts(**{t: issued.as_dict()[t] - outstanding.as_dict()[t] for t in issued.as_dict()})
    return {
        "transaction_id": str(transaction_id),
        "transaction_no": transaction_no,
        "cuffs_issued": issued,
        "cuffs_returned": returned,
        "cuffs_outstanding": outstanding,
    }


async def outstanding_by_ward(db: AsyncSession, *, ward_id: uuid.UUID | None = None) -> dict:
    rows = await cuff_crud.list_outstanding(db, ward_id=ward_id)
    wards: dict = {}
    txs: dict = {}
    for cuff, tx, eq, ward_name in rows:
        w = wards.setdefault(
            tx.ward_id,
            {"ward_id": str(tx.ward_id) if tx.ward_id else None, "ward_name": ward_name, "cuffs": dict.fromkeys(CuffCounts().as_dict(), 0), "transactions": []},
        )
        remaining = cuff.issued_count - cuff.returned_count
        w["cuffs"][cuff.cuff_type] += remaining
        t = txs.get(tx.id)
        if t is None:
            t = {
                "transaction_id": str(tx.id),
                "transaction_no": tx.transaction_no,
                "equipment_id": str(eq.id),
                "bcm_code": eq.bcm_code,
                "equipment_name": eq.equipment_name,
                "dispatched_at": tx.borrowed_at,
                "device_received": tx.status == TransactionStatus.CLOSED,
                "cuffs": dict.fromkeys(CuffCounts().as_dict(), 0),
            }
            txs[tx.id] = t
            w["transactions"].append(t)
        t["cuffs"][cuff.cuff_type] += remaining
    items = []
    total = 0
    for w in wards.values():
        w["cuffs"] = CuffCounts(**w["cuffs"])
        for t in w["transactions"]:
            t["cuffs"] = CuffCounts(**t["cuffs"])
        w["total"] = w["cuffs"].total()
        total += w["total"]
        items.append(w)
    items.sort(key=lambda w: (w["ward_name"] or "", w["ward_id"] or ""))
    return {"items": items, "total_outstanding": total}


async def reverse_receipt_return(db: AsyncSession, transaction_id: uuid.UUID, counts: CuffCounts) -> None:
    """D28: a voided receipt puts the cuffs it returned back to outstanding.
    Best effort per type: a type whose returned count is already lower (cuffs
    were adjusted separately) is left as it is."""
    for cuff_type, n in counts.as_dict().items():
        if n > 0:
            await cuff_crud.reverse_return(db, transaction_id=transaction_id, cuff_type=cuff_type, count=n)
