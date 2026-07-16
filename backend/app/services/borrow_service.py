import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    EquipmentNotAvailableError,
    EquipmentNotFoundError,
    TransactionAlreadyReturnedError,
    TransactionNotFoundError,
)
from app.core.redis import cache_delete_prefix
from app.crud import audit as audit_crud
from app.crud import equipment as equipment_crud
from app.crud import transaction as transaction_crud
from app.models.equipment import EquipmentStatus
from app.models.transaction import TX_STATUS_BORROWED, TX_STATUS_RETURNED, BorrowTransaction

RETURN_CONDITION_TO_STATUS = {
    "available": EquipmentStatus.AVAILABLE,
    "cleaning": EquipmentStatus.CLEANING,
    "pm": EquipmentStatus.PM,
    "calibration": EquipmentStatus.CALIBRATION,
    "repair": EquipmentStatus.REPAIR,
}


async def borrow(
    db: AsyncSession,
    *,
    equipment_qr: str | None,
    equipment_id: str | None,
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
    equipment = None
    if equipment_qr:
        equipment = await equipment_crud.get_by_qr(db, equipment_qr)
    elif equipment_id:
        equipment = await equipment_crud.get_by_id(db, uuid.UUID(equipment_id))

    if equipment is None:
        raise EquipmentNotFoundError("Equipment not found")

    if equipment.status != EquipmentStatus.AVAILABLE:
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
                "ward_id": uuid.UUID(ward_id) if ward_id else None,
                "department_id": uuid.UUID(department_id) if department_id else None,
                "phone_number": phone_number,
                "pickup_location_id": uuid.UUID(pickup_location_id) if pickup_location_id else None,
                "dropoff_location_id": uuid.UUID(dropoff_location_id) if dropoff_location_id else None,
                "due_at": due_at,
                "notes": notes,
                "status": TX_STATUS_BORROWED,
            },
        )
    except IntegrityError as exc:
        await db.rollback()
        raise EquipmentNotAvailableError("Equipment was just borrowed by someone else") from exc

    await equipment_crud.change_status(
        db, equipment, new_status=EquipmentStatus.BORROWED, changed_by_user_id=borrower_user_id, reason="Borrowed"
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
        raise ValueError(f"Unknown condition '{condition}'")

    tx.returned_at = datetime.utcnow()
    tx.condition_on_return = condition
    tx.status = TX_STATUS_RETURNED
    tx.received_by_user_id = received_by_user_id
    if notes:
        tx.notes = f"{tx.notes or ''}\n[Return] {notes}".strip()

    equipment = await equipment_crud.get_by_id(db, tx.equipment_id)
    if equipment is None:
        raise EquipmentNotFoundError("Equipment not found")

    await equipment_crud.change_status(
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
