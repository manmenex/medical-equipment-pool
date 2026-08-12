import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    ADMINISTRATOR_ONLY_ROLES,
    EQUIPMENT_POOL_OPERATION_ROLES,
    get_current_role_name,
    get_current_user,
    require_roles,
)
from app.core.audit import (
    AUDIT_ACTION_CREATE,
    AUDIT_ACTION_DELETE,
    AUDIT_ACTION_STATUS_CHANGE,
    AUDIT_ACTION_UPDATE,
    AUDIT_ENTITY_EQUIPMENT,
    record_audit_event,
)
from app.core.db_errors import translate_integrity_error
from app.core.exceptions import EquipmentNotFoundError, MalformedQrCodeError
from app.core.redis import cache_delete_prefix
from app.core.references import ensure_referenced_row_exists
from app.crud import equipment as equipment_crud
from app.db.session import get_db
from app.models.equipment import EquipmentStatus
from app.models.master_data import Department, EquipmentCategory, Location
from app.models.user import ROLE_ADMINISTRATOR
from app.schemas.common import Page
from app.schemas.equipment import (
    BcmSuggestion,
    EquipmentCreate,
    EquipmentOut,
    EquipmentStatusChange,
    EquipmentStatusHistoryOut,
    EquipmentUpdate,
    QrResolveRequest,
)
from app.services.identifiers import normalize_bcm_code, normalize_item_no
from app.services.qr_service import extract_item_no_from_qr
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
    """Full internal equipment state, for both audit before/after records
    and as the source dict for EquipmentOut.model_validate(...). Includes
    item_no so the audit trail stays complete — the operator-facing
    boundary (See ADR-002 / ADR-003 — knowledge/architecture/
    api-information-boundaries.md: Item No must never appear in a normal
    operator-facing response) is enforced by EquipmentOut itself not
    declaring an item_no field, not by omitting it here. Excludes
    qr_code_value (retired legacy QR value, See ADR-004 — never read by
    any active endpoint).
    """
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
        "item_no": equipment.item_no,
        "status": equipment.status,
        "bcm_code": equipment.bcm_code,
        "created_at": equipment.created_at,
        "updated_at": equipment.updated_at,
        "version": equipment.version,
    }


@router.post("/resolve-qr", response_model=EquipmentOut)
async def resolve_equipment_by_qr(
    payload: QrResolveRequest, db: AsyncSession = Depends(get_db), _user=Depends(get_current_user)
):
    """QR resolver. See ADR-004: hospital Item-No QR is the only supported
    format, resolved by exact match, never partial. A POST with a body
    (rather than the raw text embedded in a GET path) so an arbitrary
    scanned payload -- which may contain characters unsafe in a URL path,
    or, if the scanner picked up an unrelated QR code, a full external URL
    -- never lands in a server access log line via the request path/query
    string.
    """
    try:
        item_no = extract_item_no_from_qr(payload.raw_value)
    except ValueError as exc:
        raise MalformedQrCodeError(
            "The scanned QR code could not be read as a valid equipment identifier."
        ) from exc
    equipment = await equipment_crud.get_by_item_no(db, item_no)
    if equipment is None:
        raise EquipmentNotFoundError("No equipment matches the scanned QR code.")
    return EquipmentOut.model_validate(_serialize(equipment))


@router.get("/search/bcm", response_model=list[BcmSuggestion])
async def search_equipment_by_bcm(
    q: str = Query(default="", max_length=64),
    limit: int = Query(default=10, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """BCM-Code-only manual search. See ADR-003 and
    app.crud.equipment.search_bcm for matching/ranking behavior. Response
    is intentionally minimal (BcmSuggestion: id + bcm_code only) -- never
    item_no, device name, brand, model, serial number, or status.
    """
    rows = await equipment_crud.search_bcm(db, q=q, limit=limit)
    return [BcmSuggestion.model_validate({"id": str(row.id), "bcm_code": row.bcm_code}) for row in rows]


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


@router.post("", response_model=EquipmentOut, status_code=201)
async def create_equipment(
    payload: EquipmentCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    # Roadmap PR10: equipment master-data creation is Administrator-only
    # (docs/audits/03-hospital-equipment-pool-workflow-audit.md §10's matrix
    # leans Admin-only for MVP master data) -- narrowed from the pre-PR10
    # admin+biomedical_engineer gate, since biomedical_engineer has no
    # confirmed equivalent in the new 3-role model.
    user=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    data = payload.model_dump()
    # Canonicalize identifiers before write (See ADR-002;
    # app.services.identifiers) -- identical normalization for create and
    # update, so uniqueness and lookup always compare the same form.
    if data.get("bcm_code") is not None:
        data["bcm_code"] = normalize_bcm_code(data["bcm_code"])
    if data.get("item_no") is not None:
        data["item_no"] = normalize_item_no(data["item_no"])

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
    # `data` (used for the ORM write above) keeps native Python `date`
    # objects for pm_due_date/cal_due_date, which the audit row's JSON/JSONB
    # column cannot serialize directly — a create request that actually
    # supplies either field would otherwise crash here (TypeError: Object of
    # type date is not JSON serializable) after the equipment row already
    # committed. mode="json" renders dates as ISO strings instead.
    audit_after = payload.model_dump(mode="json")
    audit_after["bcm_code"] = data.get("bcm_code")
    audit_after["item_no"] = data.get("item_no")
    await record_audit_event(
        db,
        actor_user_id=user.id,
        action=AUDIT_ACTION_CREATE,
        entity_type=AUDIT_ENTITY_EQUIPMENT,
        entity_id=equipment.id,
        after=audit_after,
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
    # Roadmap PR10: same Administrator-only master-data rule as create_equipment.
    user=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    equipment = await equipment_crud.get_by_id(db, equipment_id)
    if equipment is None:
        raise EquipmentNotFoundError("Equipment not found")
    before = _serialize(equipment)

    update_data = payload.model_dump(exclude_unset=True)
    # Same canonicalization as create (See ADR-002) -- update uses an
    # identical normalization rule, never a looser one.
    if update_data.get("bcm_code") is not None:
        update_data["bcm_code"] = normalize_bcm_code(update_data["bcm_code"])
    if update_data.get("item_no") is not None:
        update_data["item_no"] = normalize_item_no(update_data["item_no"])
    for key in ("category_id", "department_owner_id", "current_location_id"):
        if key in update_data:
            update_data[key] = parse_uuid(update_data[key], key)
    await _validate_equipment_references(db, update_data)

    async with translate_integrity_error(db, resource="equipment"):
        equipment = await equipment_crud.update(db, equipment, data=update_data)
    # Roadmap PR91-H1: an empty PATCH (exclude_unset=True producing no
    # fields at all) performs no genuine Equipment mutation --
    # equipment_crud.update() itself already skips the version increment
    # for this case (see its own guard) -- so it must not produce a
    # spurious AUDIT_ACTION_UPDATE record either. A non-empty update_data
    # still records normally, even if a supplied field's value happens to
    # match the record's existing value -- that is a genuine accepted
    # update by this codebase's existing semantics, not a no-op.
    if update_data:
        # The canonicalized values actually written, not the raw request
        # body, so the audit trail matches what was persisted (See ADR-002).
        audit_after = payload.model_dump(exclude_unset=True, mode="json")
        if "bcm_code" in audit_after:
            audit_after["bcm_code"] = update_data.get("bcm_code")
        if "item_no" in audit_after:
            audit_after["item_no"] = update_data.get("item_no")
        await record_audit_event(
            db,
            actor_user_id=user.id,
            action=AUDIT_ACTION_UPDATE,
            entity_type=AUDIT_ENTITY_EQUIPMENT,
            entity_id=equipment.id,
            before={k: str(v) for k, v in before.items()},
            after=audit_after,
            request=request,
        )
    await db.commit()
    await cache_delete_prefix("equipment:search:")
    return EquipmentOut.model_validate(_serialize(equipment))


# Roadmap PR10: this single generic endpoint covers three distinct
# capabilities depending on payload.status (see
# app.models.equipment.MANUAL_LIFECYCLE_TRANSITIONS) -- marking defective
# (target UNAVAILABLE_DEFECTIVE, from AVAILABLE_AT_POOL) is allowed to
# Equipment Pool Staff, but reactivating (target AVAILABLE_AT_POOL, from
# UNAVAILABLE_DEFECTIVE) and decommissioning (target DECOMMISSIONED, from
# UNAVAILABLE_DEFECTIVE) are Administrator-only per the confirmed matrix.
# A single static `require_roles(...)` dependency cannot express a
# per-payload-value distinction, so the entry gate below only proves the
# caller is Administrator or Equipment Pool Staff; the finer distinction is
# enforced in the body, before any side effect or audit write.
EQUIPMENT_STATUS_ADMINISTRATOR_ONLY_TARGETS = frozenset(
    {EquipmentStatus.AVAILABLE_AT_POOL, EquipmentStatus.DECOMMISSIONED}
)


@router.post("/{equipment_id}/status", response_model=EquipmentOut)
async def change_equipment_status(
    equipment_id: uuid.UUID,
    payload: EquipmentStatusChange,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(*EQUIPMENT_POOL_OPERATION_ROLES)),
    role_name: str = Depends(get_current_role_name),
):
    if payload.status in EQUIPMENT_STATUS_ADMINISTRATOR_ONLY_TARGETS and role_name != ROLE_ADMINISTRATOR:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    equipment = await equipment_crud.get_by_id(db, equipment_id)
    if equipment is None:
        raise EquipmentNotFoundError("Equipment not found")
    # Roadmap PR6-H2: this generic endpoint may only perform authorized
    # maintenance-lifecycle changes -- never a dispatch or receipt
    # transition, which must stay atomic with the corresponding
    # BorrowTransaction and belongs exclusively to app.services.
    # borrow_service (See app.models.equipment.MANUAL_LIFECYCLE_TRANSITIONS).
    await equipment_crud.change_status_for_manual_lifecycle(
        db, equipment, new_status=payload.status, changed_by_user_id=user.id, reason=payload.reason
    )
    await record_audit_event(
        db,
        actor_user_id=user.id,
        action=AUDIT_ACTION_STATUS_CHANGE,
        entity_type=AUDIT_ENTITY_EQUIPMENT,
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
    user=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    equipment = await equipment_crud.get_by_id(db, equipment_id)
    if equipment is None:
        raise EquipmentNotFoundError("Equipment not found")
    before = _serialize(equipment)
    await equipment_crud.soft_delete(db, equipment)
    await record_audit_event(
        db,
        actor_user_id=user.id,
        action=AUDIT_ACTION_DELETE,
        entity_type=AUDIT_ENTITY_EQUIPMENT,
        entity_id=equipment.id,
        before={k: str(v) for k, v in before.items()},
        request=request,
    )
    await db.commit()
    await cache_delete_prefix("equipment:search:")
    await cache_delete_prefix("dashboard:")
