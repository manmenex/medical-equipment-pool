import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_errors import IntegrityViolationKind, classify_integrity_error
from app.core.exceptions import (
    EquipmentNotAvailableError,
    EquipmentNotFoundError,
    InvalidInputError,
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
from app.models.transaction import BorrowTransaction, DispatchType, RoutineRound, TransactionStatus
from app.utils.parsing import parse_uuid

# Roadmap PR6 / owner-confirmed cleaning retirement: "cleaning" is
# deliberately absent here, not remapped. Cleaning is performed as part of
# collecting/receiving equipment (AGENTS.md), not a separately recorded
# receipt outcome -- a usable receipt already becomes AVAILABLE_AT_POOL
# directly. Passing condition="cleaning" now falls through to the
# `new_status is None` branch below and is rejected as an unknown
# condition, the same as any other unrecognized value -- never silently
# accepted or routed to a status. pm/calibration/repair all classify as
# UNAVAILABLE_DEFECTIVE under the 4-state model (See
# HOSPITAL_DOMAIN_MODEL.md): each blocks dispatch pending authorized
# review, and the 4-state model has no more granular "why" status.
RETURN_CONDITION_TO_STATUS = {
    "available": EquipmentStatus.AVAILABLE_AT_POOL,
    "pm": EquipmentStatus.UNAVAILABLE_DEFECTIVE,
    "calibration": EquipmentStatus.UNAVAILABLE_DEFECTIVE,
    "repair": EquipmentStatus.UNAVAILABLE_DEFECTIVE,
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
    condition: str,
    notes: str | None,
    received_by_user_id: uuid.UUID | None,
    ip_address: str | None,
    user_agent: str | None,
) -> BorrowTransaction:
    tx = await transaction_crud.get_by_id(db, transaction_id)
    if tx is None:
        raise TransactionNotFoundError("Transaction not found")
    if tx.status != TransactionStatus.OPEN:
        raise TransactionAlreadyReturnedError("This transaction has already been returned")

    new_status = RETURN_CONDITION_TO_STATUS.get(condition)
    if new_status is None:
        raise InvalidInputError(f"Unknown condition '{condition}'")

    await transaction_crud.close(
        db, tx, received_by_user_id=received_by_user_id, condition_on_return=condition, notes=notes
    )

    equipment = await equipment_crud.get_by_id(db, tx.equipment_id)
    if equipment is None:
        raise EquipmentNotFoundError("Equipment not found")

    await equipment_crud.change_status_for_dispatch_receipt(
        db, equipment, new_status=new_status, changed_by_user_id=received_by_user_id, reason=f"Returned as {condition}"
    )
    await audit_crud.create(
        db,
        user_id=received_by_user_id,
        action="return",
        entity_type="borrow_transaction",
        entity_id=tx.id,
        after_data={"condition": condition},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await db.refresh(tx, attribute_names=["equipment"])
    await cache_delete_prefix("equipment:search:")
    await cache_delete_prefix("dashboard:")
    return tx
