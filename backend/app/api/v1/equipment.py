import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, require_roles
from app.core.audit import record_audit_event
from app.core.db_errors import translate_integrity_error
from app.core.exceptions import EquipmentNotFoundError
from app.core.redis import cache_delete_prefix
from app.core.references import ensure_referenced_row_exists
from app.crud import equipment as equipment_crud
from app.db.session import get_db
from app.models.equipment import EquipmentStatus
from app.models.master_data import Department, EquipmentCategory, Location
from app.models.user import ROLE_ADMIN, ROLE_BIOMEDICAL_ENGINEER
from app.schemas.common import Page
from app.schemas.equipment import (
    EquipmentCreate,
    EquipmentOut,
    EquipmentStatusChange,
    EquipmentStatusHistoryOut,
    EquipmentUpdate,
)
from app.services.qr_service import build_qr_value, generate_qr_png
from app.utils.parsing import parse_uuid

# Equipment's foreign-key fields, mapped to the model they reference, so a
# request can be validated against real rows before flush (see
# app.core.references) — this is also the only way to catch a bad reference
# in tests, since the SQLite test database does not enforce FK constraints.
EQUIPMENT_REFERENCE_MODELS: dict[str, type] = {
    "category_id": EquipmentCategory,
    "department_owner_id": Department,
    "current_location_id": Location,
}

router = APIRouter(prefix="/equipment", tags=["equipment"])


async def _validate_equipment_references(db: AsyncSession, data: dict) -> None:
    for field_name, model in EQUIPMENT_REFERENCE_MODELS.items():
        if field_name in data:
            await ensure_referenced_row_exists(db, model, data[field_name], field_name=field_name)


@router.get("", response_model=Page[EquipmentOut])
async def list_equipment(
    q: str | None = None,
    status: EquipmentStatus | None = None,
    department_id: str | None = None,
    category_id: str | None = None,
    limit: int = Query(default=25, le=200),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    rows, next_cursor, total = await equipment_crud.search(
        db,
        q=q,
        status=status,
        department_id=parse_uuid(department_id, "department_id"),
        category_id=parse_uuid(category_id, "category_id"),
        limit=limit,
        cursor=cursor,
    )
    items = [EquipmentOut.model_validate(_serialize(e)) for e in rows]
    return Page(items=items, next_cursor=next_cursor, total=total)


def _serialize(equipment) -> dict:
    return {
        "id": str(equipment.id),
        "asset_number": equipment.asset_number,
        "serial_number": equipment.serial_number,
        "equipment_name": equipment.equipment_name,
        "category_id": str(equipment.category_id) if equipment.category_id else None,
        "brand": equipment.brand,
        "model": equipment.model,
        "department_owner_id": str(equipment.department_owner_id) if equipment.department_owner_id else None,
        "current_location_id": str(equipment.current_location_id) if equipment.current_location_id else None,
        "pm_due_date": equipment.pm_due_date,
        "cal_due_date": equipment.cal_due_date,
        "status": equipment.status,
        "qr_code_value": equipment.qr_code_value,
        "created_at": equipment.created_at,
        "updated_at": equipment.updated_at,
    }


@router.get("/by-qr/{qr_value}", response_model=EquipmentOut)
async def get_by_qr(qr_value: str, db: AsyncSession = Depends(get_db), _user=Depends(get_current_user)):
    equipment = await equipment_crud.get_by_qr(db, qr_value)
    if equipment is None:
        raise EquipmentNotFoundError("Equipment not found for this QR code")
    return EquipmentOut.model_validate(_serialize(equipment))


@router.get("/{equipment_id}", response_model=EquipmentOut)
async def get_equipment(equipment_id: uuid.UUID, db: AsyncSession = Depends(get_db), _user=Depends(get_current_user)):
    equipment = await equipment_crud.get_by_id(db, equipment_id)
    if equipment is None:
        raise EquipmentNotFoundError("Equipment not found")
    return EquipmentOut.model_validate(_serialize(equipment))


@router.get("/{equipment_id}/history", response_model=list[EquipmentStatusHistoryOut])
async def get_equipment_history(
    equipment_id: uuid.UUID, db: AsyncSession = Depends(get_db), _user=Depends(get_current_user)
):
    history = await equipment_crud.get_history(db, equipment_id)
    return [
        EquipmentStatusHistoryOut.model_validate(
            {
                "id": str(h.id),
                "from_status": h.from_status,
                "to_status": h.to_status,
                "reason": h.reason,
                "changed_at": h.changed_at,
            }
        )
        for h in history
    ]


@router.get("/{equipment_id}/qrcode")
async def get_equipment_qrcode(
    equipment_id: uuid.UUID, db: AsyncSession = Depends(get_db), _user=Depends(get_current_user)
):
    equipment = await equipment_crud.get_by_id(db, equipment_id)
    if equipment is None:
        raise EquipmentNotFoundError("Equipment not found")
    png_bytes = generate_qr_png(equipment.qr_code_value)
    return Response(content=png_bytes, media_type="image/png")


@router.post("", response_model=EquipmentOut, status_code=201)
async def create_equipment(
    payload: EquipmentCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(ROLE_ADMIN, ROLE_BIOMEDICAL_ENGINEER)),
):
    data = payload.model_dump()
    data["qr_code_value"] = build_qr_value(payload.asset_number)

    # A separate dict for the ORM call: FK fields need real UUID objects, but
    # `data` itself is reused below as the audit log's after_data, which is
    # JSON-serialized and must keep plain strings (uuid.UUID isn't
    # JSON-serializable by the default encoder).
    create_data = dict(data)
    for key in ("category_id", "department_owner_id", "current_location_id"):
        create_data[key] = parse_uuid(data.get(key), key)
    await _validate_equipment_references(db, create_data)

    async with translate_integrity_error(db, resource="equipment"):
        equipment = await equipment_crud.create(db, data=create_data)
    await record_audit_event(
        db,
        actor_user_id=user.id,
        action="create",
        entity_type="equipment",
        entity_id=equipment.id,
        after=data,
        request=request,
    )
    await db.commit()
    await cache_delete_prefix("equipment:search:")
    await cache_delete_prefix("dashboard:")
    return EquipmentOut.model_validate(_serialize(equipment))


@router.patch("/{equipment_id}", response_model=EquipmentOut)
async def update_equipment(
    equipment_id: uuid.UUID,
    payload: EquipmentUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(ROLE_ADMIN, ROLE_BIOMEDICAL_ENGINEER)),
):
    equipment = await equipment_crud.get_by_id(db, equipment_id)
    if equipment is None:
        raise EquipmentNotFoundError("Equipment not found")
    before = _serialize(equipment)

    update_data = payload.model_dump(exclude_unset=True)
    for key in ("category_id", "department_owner_id", "current_location_id"):
        if key in update_data:
            update_data[key] = parse_uuid(update_data[key], key)
    await _validate_equipment_references(db, update_data)

    async with translate_integrity_error(db, resource="equipment"):
        equipment = await equipment_crud.update(db, equipment, data=update_data)
    await record_audit_event(
        db,
        actor_user_id=user.id,
        action="update",
        entity_type="equipment",
        entity_id=equipment.id,
        before={k: str(v) for k, v in before.items()},
        after=payload.model_dump(exclude_unset=True, mode="json"),
        request=request,
    )
    await db.commit()
    await cache_delete_prefix("equipment:search:")
    return EquipmentOut.model_validate(_serialize(equipment))


@router.post("/{equipment_id}/status", response_model=EquipmentOut)
async def change_equipment_status(
    equipment_id: uuid.UUID,
    payload: EquipmentStatusChange,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(ROLE_ADMIN, ROLE_BIOMEDICAL_ENGINEER)),
):
    equipment = await equipment_crud.get_by_id(db, equipment_id)
    if equipment is None:
        raise EquipmentNotFoundError("Equipment not found")
    await equipment_crud.change_status(
        db, equipment, new_status=payload.status, changed_by_user_id=user.id, reason=payload.reason
    )
    await record_audit_event(
        db,
        actor_user_id=user.id,
        action="status_change",
        entity_type="equipment",
        entity_id=equipment.id,
        after={"status": payload.status.value, "reason": payload.reason},
        request=request,
    )
    await db.commit()
    await cache_delete_prefix("equipment:search:")
    await cache_delete_prefix("dashboard:")
    return EquipmentOut.model_validate(_serialize(equipment))


@router.delete("/{equipment_id}", status_code=204)
async def delete_equipment(
    equipment_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(ROLE_ADMIN)),
):
    equipment = await equipment_crud.get_by_id(db, equipment_id)
    if equipment is None:
        raise EquipmentNotFoundError("Equipment not found")
    await equipment_crud.soft_delete(db, equipment)
    await record_audit_event(
        db,
        actor_user_id=user.id,
        action="delete",
        entity_type="equipment",
        entity_id=equipment.id,
        request=request,
    )
    await db.commit()
    await cache_delete_prefix("equipment:search:")
    await cache_delete_prefix("dashboard:")
