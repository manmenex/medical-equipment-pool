"""Roadmap PR28 (D4/D10): which accessory checklist applies, and checklist
validation against it.

The kind comes from master data (``equipment_categories.checklist_kind``), not
a runtime name match; see ``app.models.master_data.EquipmentCategory``.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ChecklistKindMismatchError
from app.models.master_data import EquipmentCategory
from app.schemas.checklist import CHECKLIST_CRYO_CUFF, CHECKLIST_STANDARD, CryoCuffChecks, StandardChecks

DEFAULT_CRYO_NAME_MARKER = "cryo"


def default_kind_for_category_name(name: str) -> str:
    """Default applied when a category is created without an explicit kind
    (and by migration 0031's backfill): names containing "cryo",
    case-insensitive, are Cryo-Cuff."""
    return CHECKLIST_CRYO_CUFF if DEFAULT_CRYO_NAME_MARKER in name.lower() else CHECKLIST_STANDARD


async def kind_for_equipment(db: AsyncSession, equipment) -> str:
    if equipment.category_id is None:
        return CHECKLIST_STANDARD
    kind = (
        await db.execute(select(EquipmentCategory.checklist_kind).where(EquipmentCategory.id == equipment.category_id))
    ).scalar_one_or_none()
    return kind or CHECKLIST_STANDARD


def ensure_kind_matches(checks: StandardChecks | CryoCuffChecks | None, expected_kind: str) -> None:
    if checks is not None and checks.kind != expected_kind:
        raise ChecklistKindMismatchError(
            f"This equipment uses the '{expected_kind}' checklist; got '{checks.kind}'.",
            details={"expected_kind": expected_kind, "received_kind": checks.kind},
        )
