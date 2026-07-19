import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    EquipmentNotAvailableError,
    EquipmentNotFoundError,
    InvalidInputError,
    TransactionAlreadyReturnedError,
    TransactionNotFoundError,
)
from app.core.redis import cache_delete_prefix
from app.crud import audit as audit_crud
from app.crud import equipment as equipment_crud
from app.crud import transaction as transaction_crud
from app.models.equipment import EquipmentStatus
from app.models.transaction import TX_STATUS_BORROWED, TX_STATUS_RETURNED, BorrowTransaction
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
    borrower_name: str,
    ward_id: str | None,
    department_id: str | None,
    phone_number: str | None,
    pickup_location_id: str | None,
    dropoff_location_id: str | None,
    quantity: int,
    due_at,
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

    transaction_no = await transaction_crud.generate_transaction_no(db)

    try:
        tx = await transaction_crud.create(
            db,
            data={
                "transaction_no": transaction_no,
                "equipment_id": equipment.id,
                "quantity": quantity,
                "borrower_user_id": borrower_user_id,
                "borrower_name": borrower_name,
                "ward_id": parse_uuid(ward_id, "ward_id"),
                "department_id": parse_uuid(department_id, "department_id"),
                "phone_number": phone_number,
                "pickup_location_id": parse_uuid(pickup_location_id, "pickup_location_id"),
                "dropoff_location_id": parse_uuid(dropoff_location_id, "dropoff_location_id"),
                "due_at": due_at,
                "notes": notes,
                "status": TX_STATUS_BORROWED,
            },
        )
    except IntegrityError as exc:
        await db.rollback()
        raise EquipmentNotAvailableError("Equipment was just borrowed by someone else") from exc

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
    from datetime import datetime

    tx = await transaction_crud.get_by_id(db, transaction_id)
    if tx is None:
        raise TransactionNotFoundError("Transaction not found")
    if tx.status != TX_STATUS_BORROWED:
        raise TransactionAlreadyReturnedError("This transaction has already been returned")

    new_status = RETURN_CONDITION_TO_STATUS.get(condition)
    if new_status is None:
        raise InvalidInputError(f"Unknown condition '{condition}'")

    tx.returned_at = datetime.utcnow()
    tx.condition_on_return = condition
    tx.status = TX_STATUS_RETURNED
    tx.received_by_user_id = received_by_user_id
    if notes:
        tx.notes = f"{tx.notes or ''}\n[Return] {notes}".strip()

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
