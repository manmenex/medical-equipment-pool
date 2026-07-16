"""Hospital medical device inventory model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional


@dataclass(slots=True)
class InventoryItem:
    """One hospital-owned medical device, imported from the Excel inventory.

    `equipment_code` / `asset_number` are the hospital's own identifiers;
    `udi`, `model_number` and `catalog_number` are the fields the matching
    engine prefers, in priority order, when comparing against recalls.
    """

    asset_number: str
    equipment_code: str = ""
    device_name: str = ""
    manufacturer: str = ""
    brand: str = ""
    model_number: str = ""
    catalog_number: str = ""
    udi: str = ""
    serial_number: str = ""
    department: str = ""
    location: str = ""
    purchase_date: Optional[date] = None
    status: str = ""
    extra_fields: dict[str, Any] = field(default_factory=dict)
    imported_at: datetime = field(default_factory=datetime.now)

    id: Optional[int] = None

    def natural_key(self) -> str:
        return f"INV::{self.asset_number}"
