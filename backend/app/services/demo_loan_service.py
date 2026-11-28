"""Roadmap PR33 (Owner Governance 2026-11-26, D14): administrator batch
registration of demo/loan devices.

One shared header (category, brand, model, source, owner company, optional
due-back date) plus one row per manufacturer serial number. For demo/loan
devices ONLY the serial number is stored in ``bcm_code`` (narrow amendment to
ADR-002; the four-identifier model is unchanged). Pool BCM rules are not
touched. Uniqueness is across ALL equipment (the plain unique index on
``bcm_code``), so a serial can never collide with a pool BCM Code either.

``validate_batch`` is read-only (dry run). ``commit_batch`` re-validates and
writes everything in one transaction -- all rows or none.
"""
import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidInputError
from app.core.references import ensure_referenced_row_exists
from app.crud import equipment as equipment_crud
from app.models.equipment import Equipment
from app.models.master_data import EquipmentCategory
from app.schemas.equipment import DemoLoanBatchRequest
from app.services.identifiers import normalize_serial_as_bcm_code
from app.utils.parsing import parse_uuid

ERR_BLANK = "blank"
ERR_INVALID = "invalid_serial"
ERR_DUP_BATCH = "duplicate_in_batch"
ERR_DUP_DB = "duplicate_in_db"


@dataclass
class RowResult:
    index: int
    serial_number: str
    errors: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


async def validate_batch(db: AsyncSession, payload: DemoLoanBatchRequest) -> list[RowResult]:
    """Per-row validation; also checks the shared category exists (a bad
    category is a request-level 4xx, not a row error)."""
    category_id = parse_uuid(payload.shared.category_id, "category_id")
    await ensure_referenced_row_exists(db, EquipmentCategory, category_id, field_name="category_id")

    rows: list[RowResult] = []
    normalized: dict[int, str] = {}
    for i, item in enumerate(payload.items):
        raw = item.serial_number or ""
        row = RowResult(index=i, serial_number=raw.strip())
        if not raw.strip():
            row.errors.append(ERR_BLANK)
            row.messages.append("Serial number is blank.")
        else:
            try:
                canonical = normalize_serial_as_bcm_code(raw)
            except InvalidInputError as exc:
                row.errors.append(ERR_INVALID)
                row.messages.append(exc.message if hasattr(exc, "message") else str(exc))
            else:
                row.serial_number = canonical
                normalized[i] = canonical
        rows.append(row)

    seen: dict[str, int] = {}
    for i, canonical in normalized.items():
        if canonical in seen:
            rows[i].errors.append(ERR_DUP_BATCH)
            rows[i].messages.append(f"Duplicate of row {seen[canonical] + 1} in this batch.")
            # The first occurrence is not itself an error; only repeats are flagged.
        else:
            seen[canonical] = i

    existing = await equipment_crud.get_existing_bcm_codes(db, list(set(normalized.values())))
    for i, canonical in normalized.items():
        if canonical in existing:
            rows[i].errors.append(ERR_DUP_DB)
            rows[i].messages.append("This serial number is already registered.")
    return rows


def batch_is_valid(rows: list[RowResult]) -> bool:
    return all(not r.errors for r in rows)


def default_equipment_name(payload: DemoLoanBatchRequest, category_name: str | None) -> str:
    shared = payload.shared
    if shared.equipment_name:
        return shared.equipment_name
    joined = " ".join(part for part in (shared.brand, shared.model) if part)
    return joined or category_name or "Demo/Loan equipment"


async def build_equipment(db: AsyncSession, payload: DemoLoanBatchRequest, rows: list[RowResult]) -> list[Equipment]:
    """Create (flush only) one Equipment per row. Caller commits. Rows must
    already be valid."""
    shared = payload.shared
    category_id = uuid.UUID(str(shared.category_id))
    category = await db.get(EquipmentCategory, category_id)
    name = default_equipment_name(payload, category.name if category is not None else None)
    created: list[Equipment] = []
    for row, item in zip(rows, payload.items):
        equipment = await equipment_crud.create(
            db,
            data={
                "equipment_name": name,
                "category_id": category_id,
                "brand": shared.brand,
                "model": shared.model,
                "bcm_code": row.serial_number,
                "equipment_source": shared.equipment_source,
                "owner_company": shared.owner_company,
                "due_back_date": shared.due_back_date,
                "has_charger": item.has_charger,
                "has_clamp": item.has_clamp,
            },
        )
        created.append(equipment)
    return created
