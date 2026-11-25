"""Roadmap PR27 (D3): ward-first batch dispatch / receipt.

Each item goes through ``borrow_service.borrow`` / ``return_equipment`` exactly
like a single request, so each item is its own database transaction (the
services commit on success and roll back on failure). A failing item is
reported in its result and never affects the others. The batch itself owns no
lifecycle logic.
"""
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DomainError, TransactionNotFoundError
from app.core.references import ensure_referenced_row_exists
from app.crud import cuff as cuff_crud
from app.crud import transaction as transaction_crud
from app.models.master_data import Ward
from app.schemas.batch import (
    BatchItemError,
    BatchItemResult,
    BatchResponse,
    DispatchBatchRequest,
    ReceiptBatchRequest,
)
from app.schemas.checklist import CuffCounts
from app.services import borrow_service

logger = logging.getLogger(__name__)


async def _outstanding(db: AsyncSession, transaction_id: uuid.UUID) -> CuffCounts | None:
    balance = (await cuff_crud.balances_for_transactions(db, [transaction_id])).get(transaction_id)
    return cuff_crud.outstanding_counts(balance) if balance else None


def _failure(index: int, equipment_id: str | None, exc: DomainError) -> BatchItemResult:
    return BatchItemResult(
        index=index,
        ok=False,
        equipment_id=equipment_id,
        error=BatchItemError(code=exc.code, message=exc.message, status=exc.status_code, details=exc.details),
    )


def _unexpected(index: int, equipment_id: str | None) -> BatchItemResult:
    return BatchItemResult(
        index=index,
        ok=False,
        equipment_id=equipment_id,
        error=BatchItemError(code="INTERNAL_ERROR", message="An unexpected error occurred.", status=500),
    )


def _response(results: list[BatchItemResult]) -> BatchResponse:
    ok = sum(1 for r in results if r.ok)
    return BatchResponse(total=len(results), succeeded=ok, failed=len(results) - ok, results=results)


async def dispatch_batch(
    db: AsyncSession,
    payload: DispatchBatchRequest,
    *,
    user_id: uuid.UUID,
    ip_address: str | None,
    user_agent: str | None,
) -> BatchResponse:
    # The shared ward is validated once: a bad ward fails the whole request
    # (nothing is written), not N identical item errors.
    await ensure_referenced_row_exists(db, Ward, payload.ward_id, field_name="ward_id")
    results: list[BatchItemResult] = []
    for index, item in enumerate(payload.items):
        equipment_id = str(item.equipment_id)
        try:
            tx = await borrow_service.borrow(
                db,
                equipment_id=equipment_id,
                borrower_user_id=user_id,
                ward_id=str(payload.ward_id),
                dispatch_type=None,
                routine_round=None,
                department_id=None,
                phone_number=payload.phone,
                pickup_location_id=None,
                dropoff_location_id=None,
                notes=payload.note,
                ip_address=ip_address,
                user_agent=user_agent,
                acknowledge_status_warning=item.acknowledge_status_warning,
                expected_open_transaction_id=item.expected_open_transaction_id,
                ward_contact_name=payload.ward_contact_name,
                dispatch_checks=item.checks,
                expected_status=item.expected_status,
            )
            tx_id, tx_no = tx.id, tx.transaction_no
            results.append(
                BatchItemResult(
                    index=index,
                    ok=True,
                    equipment_id=equipment_id,
                    transaction_id=str(tx_id),
                    transaction_no=tx_no,
                    cuffs_outstanding=await _outstanding(db, tx_id),
                )
            )
        except DomainError as exc:
            await db.rollback()
            results.append(_failure(index, equipment_id, exc))
        except Exception:
            await db.rollback()
            logger.exception("dispatch-batch item %s failed unexpectedly", index)
            results.append(_unexpected(index, equipment_id))
    return _response(results)


async def receipt_batch(
    db: AsyncSession,
    payload: ReceiptBatchRequest,
    *,
    user_id: uuid.UUID,
    ip_address: str | None,
    user_agent: str | None,
) -> BatchResponse:
    if payload.ward_id is not None:
        await ensure_referenced_row_exists(db, Ward, payload.ward_id, field_name="ward_id")
    results: list[BatchItemResult] = []
    for index, item in enumerate(payload.items):
        equipment_id = str(item.equipment_id) if item.equipment_id else None
        try:
            if item.transaction_id is not None:
                transaction_id = item.transaction_id
            else:
                open_tx = await transaction_crud.get_open_transaction_for_equipment(db, item.equipment_id)
                if open_tx is None:
                    raise TransactionNotFoundError("This equipment has no open dispatch to receive")
                transaction_id = open_tx.id
            tx = await borrow_service.return_equipment(
                db,
                transaction_id=transaction_id,
                receipt_outcome=item.receipt_outcome,
                notes=payload.note,
                received_by_user_id=user_id,
                ip_address=ip_address,
                user_agent=user_agent,
                ward_contact_name=payload.ward_contact_name,
                receipt_checks=item.checks,
                cuffs_returned=item.cuffs_returned,
            )
            tx_id, tx_no, eq_id = tx.id, tx.transaction_no, str(tx.equipment_id)
            results.append(
                BatchItemResult(
                    index=index,
                    ok=True,
                    equipment_id=eq_id,
                    transaction_id=str(tx_id),
                    transaction_no=tx_no,
                    cuffs_outstanding=await _outstanding(db, tx_id),
                )
            )
        except DomainError as exc:
            await db.rollback()
            results.append(_failure(index, equipment_id, exc))
        except Exception:
            await db.rollback()
            logger.exception("receipt-batch item %s failed unexpectedly", index)
            results.append(_unexpected(index, equipment_id))
    return _response(results)
