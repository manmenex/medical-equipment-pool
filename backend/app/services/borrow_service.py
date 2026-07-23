import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_errors import IntegrityViolationKind, classify_integrity_error
from app.core.exceptions import (
    EquipmentNotAvailableError,
    EquipmentNotFoundError,
    InvalidInputError,
    ReceiptRaceLostError,
    TransactionAlreadyReturnedError,
    TransactionNotFoundError,
)
from app.core.redis import cache_delete_prefix
from app.core.references import ensure_referenced_row_exists
from app.crud import audit as audit_crud
from app.crud import equipment as equipment_crud
from app.crud import transaction as transaction_crud
from app.models.equipment import EquipmentStatus
from app.models.master_data import Ward
from app.models.transaction import BorrowTransaction, DispatchType, ReceiptOutcome, RoutineRound, TransactionStatus
from app.utils.parsing import parse_uuid

# Roadmap PR8B (knowledge/adr/ADR-006-receipt-outcome-contract.md): the
# frozen binary receipt contract. Replaces the pre-PR8B four-value
# RETURN_CONDITION_TO_STATUS dict (`available`/`pm`/`calibration`/
# `repair`) -- a `ReceiptOutcome` is validated by app.schemas.transaction.
# ReturnRequest before this service ever runs, so this mapping is total
# over the enum's members; there is no "unknown outcome" branch to guard
# here anymore (see return_equipment below). Cleaning remains deliberately
# absent (Roadmap PR6 / owner-confirmed cleaning retirement, AGENTS.md): a
# usable receipt already becomes AVAILABLE_AT_POOL directly, and cleaning
# is never a distinct receipt outcome.
RECEIPT_OUTCOME_TO_STATUS = {
    ReceiptOutcome.USABLE: EquipmentStatus.AVAILABLE_AT_POOL,
    ReceiptOutcome.DEFECTIVE: EquipmentStatus.UNAVAILABLE_DEFECTIVE,
}


async def borrow(
    db: AsyncSession,
    *,
    equipment_id: str,
    borrower_user_id: uuid.UUID | None,
    ward_id: str,
    dispatch_type: DispatchType,
    routine_round: RoutineRound | None,
    department_id: str | None,
    phone_number: str | None,
    pickup_location_id: str | None,
    dropoff_location_id: str | None,
    notes: str | None,
    ip_address: str | None,
    user_agent: str | None,
) -> BorrowTransaction:
    # Equipment selection is always by internal UUID (See ADR-002): a QR
    # scan resolves to one via POST /equipment/resolve-qr first (exact
    # Item No match, See ADR-004), and manual selection resolves one via a
    # BCM Code suggestion (See ADR-003) -- this endpoint itself never
    # accepts a raw scanned/typed identifier.
    equipment = await equipment_crud.get_by_id(db, parse_uuid(equipment_id, "equipment_id"))

    if equipment is None:
        raise EquipmentNotFoundError("Equipment not found")

    # Roadmap PR6: dispatch eligibility is exactly this equality, never a
    # negative check like `!= ISSUED_TO_WARD` -- a broad negative check
    # would accidentally allow UNAVAILABLE_DEFECTIVE or DECOMMISSIONED
    # equipment to dispatch.
    if equipment.status != EquipmentStatus.AVAILABLE_AT_POOL:
        raise EquipmentNotAvailableError(f"Equipment is currently in status '{equipment.status.value}'")

    # Codex PR20 review round 1, MAJOR 3: ward_id is required (Roadmap
    # PR7b), so an invalid reference here is a genuine, common client input
    # error, not the rare concurrent-dispatch race the IntegrityError
    # handler below exists for -- it must not surface as "Equipment was
    # just borrowed by someone else". Validated proactively, the same
    # pattern app.api.v1.equipment/master_data already use for their own
    # foreign-key fields (see app.core.references), so it is a 400
    # InvalidInputError (code INVALID_INPUT) on both SQLite (which does not
    # enforce FK constraints) and PostgreSQL alike, and the IntegrityError
    # handler below is only ever reached for a genuine unique-index
    # collision.
    ward_uuid = parse_uuid(ward_id, "ward_id")
    await ensure_referenced_row_exists(db, Ward, ward_uuid, field_name="ward_id")

    transaction_no = await transaction_crud.generate_transaction_no(db)

    # Roadmap PR7b: ward_id and dispatch_type are required for every new
    # dispatch (docs/audits/04-consolidated-implementation-plan.md's
    # confirmed acceptance criteria); routine_round/on-demand consistency
    # is already validated by app.schemas.transaction.BorrowRequest before
    # this service is ever called. quantity/due_at/borrower_name are no
    # longer accepted here at all -- quantity and borrower_name rely on
    # their column defaults (1 and NULL respectively); due_at is never set
    # by a new dispatch (ADR-005 decision 3).
    try:
        tx = await transaction_crud.create(
            db,
            data={
                "transaction_no": transaction_no,
                "equipment_id": equipment.id,
                "borrower_user_id": borrower_user_id,
                "ward_id": ward_uuid,
                "dispatch_type": dispatch_type,
                "routine_round": routine_round,
                "department_id": parse_uuid(department_id, "department_id"),
                "phone_number": phone_number,
                "pickup_location_id": parse_uuid(pickup_location_id, "pickup_location_id"),
                "dropoff_location_id": parse_uuid(dropoff_location_id, "dropoff_location_id"),
                "notes": notes,
            },
        )
    except IntegrityError as exc:
        await db.rollback()
        # Codex PR20 review round 1, MAJOR 3: only a genuine unique-index
        # collision (idx_tx_one_active_borrow -- two concurrent dispatches
        # of the same equipment) maps to the existing concurrency response.
        # ward_id is already validated above, so a foreign-key violation
        # reaching here would mean the ward was deleted in the narrow
        # window between that check and this flush -- still a bad
        # reference, not an equipment conflict -- and any other
        # classification is treated the same way: never silently
        # mislabeled as "Equipment was just borrowed by someone else".
        if classify_integrity_error(exc) is IntegrityViolationKind.UNIQUE:
            raise EquipmentNotAvailableError("Equipment was just borrowed by someone else") from exc
        raise InvalidInputError("This dispatch references data that is no longer valid.") from exc

    await equipment_crud.change_status_for_dispatch_receipt(
        db, equipment, new_status=EquipmentStatus.ISSUED_TO_WARD, changed_by_user_id=borrower_user_id, reason="Dispatched"
    )
    await audit_crud.create(
        db,
        user_id=borrower_user_id,
        action="borrow",
        entity_type="borrow_transaction",
        entity_id=tx.id,
        after_data={"transaction_no": tx.transaction_no, "equipment_id": str(equipment.id)},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await cache_delete_prefix("equipment:search:")
    await cache_delete_prefix("dashboard:")
    return tx


async def return_equipment(
    db: AsyncSession,
    *,
    transaction_id: uuid.UUID,
    receipt_outcome: ReceiptOutcome,
    notes: str | None,
    received_by_user_id: uuid.UUID | None,
    ip_address: str | None,
    user_agent: str | None,
) -> BorrowTransaction:
    tx = await transaction_crud.get_by_id(db, transaction_id)
    if tx is None:
        raise TransactionNotFoundError("Transaction not found")

    # Roadmap PR8A Case A -- genuine sequential repeat. The row was already
    # CLOSED before this request even read it (e.g. a refresh/re-submit after
    # a receipt that already completed), so reject immediately without
    # attempting any write. This is a cheap fast-path, NOT the concurrency
    # guard: two truly concurrent requests both read status == OPEN here and
    # both pass this check -- the guard that separates them is the conditional
    # UPDATE below. See docs/design/PR8_IMPLEMENTATION_PLAN.md Section 3.
    #
    # Roadmap PR8C: this is the ONLY branch that may raise
    # TransactionAlreadyReturnedError -- a request reaching here observed a
    # transaction that was not OPEN at the moment it read it, which is a
    # genuine duplicate/repeat submission, not a timing race with another
    # in-flight request.
    if tx.status != TransactionStatus.OPEN:
        raise TransactionAlreadyReturnedError("This transaction has already been returned")

    # Roadmap PR8B: receipt_outcome is a `ReceiptOutcome`, already validated
    # by app.schemas.transaction.ReturnRequest before this service ever
    # runs -- RECEIPT_OUTCOME_TO_STATUS is total over the enum's members, so
    # there is no "unknown outcome" branch to guard here (contrast the
    # pre-PR8B free-form `condition` string, which needed one).
    new_status = RECEIPT_OUTCOME_TO_STATUS[receipt_outcome]

    # Roadmap PR8A -- the sole concurrency guard for the receipt race: a
    # conditional close (UPDATE ... WHERE status = 'open') decided by affected
    # -row count. Exactly one of N concurrent receipts for this transaction
    # gets won == True; the rest get won == False.
    won = await transaction_crud.close(
        db, tx, received_by_user_id=received_by_user_id, receipt_outcome=receipt_outcome.value, notes=notes
    )
    if not won:
        # Roadmap PR8A Case B -- lost a concurrent race. Another request
        # transitioned this row open -> closed between our read (above, which
        # observed OPEN -- otherwise Case A would already have rejected this
        # request) and our own conditional UPDATE. We return here BEFORE any
        # equipment-status, status-history, or audit write, so a losing
        # request produces zero side effects. Roll back the (row-count-zero)
        # UPDATE and the read, then reject.
        #
        # Roadmap PR8C (knowledge/adr/ADR-006-receipt-outcome-contract.md's
        # "Not decided here"): this branch is the ONLY one that may raise
        # ReceiptRaceLostError, a distinct code/class from
        # TransactionAlreadyReturnedError -- this requester did nothing
        # wrong (no prior receipt existed when their request read the row),
        # so "this transaction has already been returned" would misdescribe
        # the cause as a duplicate submission rather than a timing race with
        # another concurrent, equally legitimate request. Same HTTP status
        # (409) as Case A -- both are conflicts with current state -- but a
        # different, stable, machine-readable `code` so a caller (the
        # frontend, or any future API client) can distinguish the two
        # without parsing free-text `detail`.
        await db.rollback()
        raise ReceiptRaceLostError(
            "This equipment was just received by someone else. Refresh to see the current record."
        )

    # The conditional UPDATE executed as Core SQL, bypassing the ORM unit of
    # work, so the in-memory ``tx`` still reads OPEN with no receipt fields.
    # Refresh it so every subsequent use -- the equipment transition below and
    # the serialized response -- reflects the committed CLOSED state and never
    # a stale in-memory status (Roadmap PR8A requirement 3). The refresh runs
    # inside this same transaction and therefore sees this session's own,
    # not-yet-committed, winning UPDATE.
    await db.refresh(
        tx,
        attribute_names=["status", "returned_at", "condition_on_return", "received_by_user_id", "notes"],
    )

    equipment = await equipment_crud.get_by_id(db, tx.equipment_id)
    if equipment is None:
        raise EquipmentNotFoundError("Equipment not found")

    await equipment_crud.change_status_for_dispatch_receipt(
        db,
        equipment,
        new_status=new_status,
        changed_by_user_id=received_by_user_id,
        reason=f"Returned as {receipt_outcome.value}",
    )
    await audit_crud.create(
        db,
        user_id=received_by_user_id,
        action="return",
        entity_type="borrow_transaction",
        entity_id=tx.id,
        after_data={"receipt_outcome": receipt_outcome.value},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await db.refresh(tx, attribute_names=["equipment"])
    await cache_delete_prefix("equipment:search:")
    await cache_delete_prefix("dashboard:")
    return tx
