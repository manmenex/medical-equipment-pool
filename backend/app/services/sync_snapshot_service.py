"""Roadmap PR25E slice B3 -- reference snapshot pages for the offline client
(docs/design/PR25D_OFFLINE_OPERATION_PLAN.md sections 3.2, 3.4, 6.5).

Information boundary (knowledge/architecture/api-information-boundaries.md):
every row is built from an explicit per-section allow-list, never from an ORM
dump or a shared schema, so Item No, Asset Number, serial, QR value and every
other identifier cannot appear by accident. BCM Code is the operator-facing
search key and is allowed; Item No is excluded (ADR-004 / D1).
"""
import base64
import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidInputError
from app.models.equipment import Equipment
from app.models.master_data import Department, EquipmentCategory, Location, Ward
from app.models.transaction import BorrowTransaction, TransactionStatus

DEFAULT_LIMIT = 200
MAX_LIMIT = 500

# The allow-lists are the contract; tests assert responses match them exactly.
SECTION_FIELDS: dict[str, tuple[str, ...]] = {
    "equipment": ("id", "bcm_code", "equipment_name", "category_id", "category_name", "status"),
    "wards": ("id", "code", "name", "department_id", "phone"),
    "departments": ("id", "code", "name", "phone"),
    "locations": ("id", "name", "type"),
    "open_transactions": ("id", "equipment_id", "ward_id", "borrowed_at"),
}
SECTIONS = tuple(SECTION_FIELDS)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def encode_cursor(key: str | None, row_id: uuid.UUID) -> str:
    raw = json.dumps({"k": key, "i": str(row_id)}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str, timestamped: bool) -> tuple[datetime | None, uuid.UUID]:
    try:
        raw = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        row_id = uuid.UUID(raw["i"])
        key = datetime.fromisoformat(raw["k"]) if timestamped else None
        if key is not None and key.tzinfo is None:
            key = key.replace(tzinfo=timezone.utc)
        if timestamped and key is None:
            raise ValueError
        return key, row_id
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise InvalidInputError("Invalid snapshot cursor.") from exc


def _after(ts_col, id_col, key, row_id):
    if ts_col is None:
        return id_col > row_id
    return or_(ts_col > key, and_(ts_col == key, id_col > row_id))


async def get_page(db: AsyncSession, section: str, cursor: str | None, limit: int) -> dict:
    """One deterministically ordered page: ``(updated_at, id)`` for equipment,
    ``(borrowed_at, id)`` for open transactions, ``id`` for tables that carry no
    timestamp. Returns rows plus ``next_cursor`` and a content ETag."""
    if section not in SECTION_FIELDS:
        raise InvalidInputError(f"Unknown snapshot section. Allowed: {', '.join(SECTIONS)}.")
    limit = max(1, min(limit, MAX_LIMIT))

    if section == "equipment":
        model, ts_col = Equipment, Equipment.updated_at
        stmt = (
            select(Equipment, EquipmentCategory.name)
            .outerjoin(EquipmentCategory, EquipmentCategory.id == Equipment.category_id)
            .where(Equipment.deleted_at.is_(None))
        )
    elif section == "open_transactions":
        model, ts_col = BorrowTransaction, BorrowTransaction.borrowed_at
        stmt = select(BorrowTransaction).where(BorrowTransaction.status == TransactionStatus.OPEN)
    else:
        model = {"wards": Ward, "departments": Department, "locations": Location}[section]
        ts_col = None
        stmt = select(model)

    if cursor:
        key, row_id = decode_cursor(cursor, ts_col is not None)
        stmt = stmt.where(_after(ts_col, model.id, key, row_id))
    order = (ts_col, model.id) if ts_col is not None else (model.id,)
    result = await db.execute(stmt.order_by(*order).limit(limit + 1))
    rows = result.all()
    more = len(rows) > limit
    rows = rows[:limit]

    items: list[dict] = []
    last = None
    for row in rows:
        if section == "equipment":
            obj, category_name = row
            item = {
                "id": str(obj.id),
                "bcm_code": obj.bcm_code,
                "equipment_name": obj.equipment_name,
                "category_id": str(obj.category_id) if obj.category_id else None,
                "category_name": category_name,
                "status": obj.status.value,
            }
        else:
            obj = row[0]
            if section == "open_transactions":
                item = {
                    "id": str(obj.id),
                    "equipment_id": str(obj.equipment_id),
                    "ward_id": str(obj.ward_id) if obj.ward_id else None,
                    "borrowed_at": _iso(obj.borrowed_at),
                }
            elif section == "wards":
                item = {
                    "id": str(obj.id), "code": obj.code, "name": obj.name,
                    "department_id": str(obj.department_id) if obj.department_id else None, "phone": obj.phone,
                }
            elif section == "departments":
                item = {"id": str(obj.id), "code": obj.code, "name": obj.name, "phone": obj.phone}
            else:
                item = {"id": str(obj.id), "name": obj.name, "type": obj.type}
        assert tuple(item) == SECTION_FIELDS[section]
        items.append(item)
        last = obj

    next_cursor = None
    if more and last is not None:
        next_cursor = encode_cursor(_iso(getattr(last, ts_col.key)) if ts_col is not None else None, last.id)
    digest = hashlib.sha256(
        json.dumps({"s": section, "i": items, "n": next_cursor}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:32]
    return {
        "section": section,
        "items": items,
        "next_cursor": next_cursor,
        "etag": f'"{digest}"',
        "server_time": datetime.now(timezone.utc),
    }
