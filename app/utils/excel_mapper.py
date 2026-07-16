"""
Automatic column mapping for hospital inventory Excel imports (FUNCTION 3).

Hospitals name their inventory columns differently ("Asset #", "Asset Tag",
"Asset Number" all mean the same thing). This module maps whatever headers
are actually in the uploaded spreadsheet onto the canonical
`InventoryItem` fields using:

    1. Exact match against a synonym table (`_ALIASES`), case/punctuation
       insensitive - fast and unambiguous.
    2. RapidFuzz fuzzy matching against the same synonym table for any
       column that didn't match exactly, so close-but-not-identical
       headers ("Assett Number", "Mfr.") still map correctly.

Only `asset_number` is strictly required; every other canonical field is
best-effort. Any source column that cannot be mapped to a canonical field
is preserved in `InventoryItem.extra_fields` rather than dropped, so no
hospital data is silently lost.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from app.utils.exceptions import MissingColumnsError

REQUIRED_FIELDS = ("asset_number",)

# canonical field -> known synonyms (lowercase, alnum-only compare)
_ALIASES: dict[str, list[str]] = {
    "equipment_code": ["equipment code", "equipmentcode", "equipment id", "eq code"],
    "asset_number": [
        "asset number",
        "asset no",
        "asset #",
        "asset tag",
        "assetnumber",
        "asset id",
        "assettag",
        "tag number",
    ],
    "device_name": ["device name", "equipment name", "product name", "device", "item name", "description"],
    "manufacturer": ["manufacturer", "mfr", "maker", "oem", "vendor"],
    "brand": ["brand", "brand name"],
    "model_number": ["model", "model number", "model no", "model #"],
    "catalog_number": ["catalog number", "catalog no", "catalog #", "cat no", "part number"],
    "udi": ["udi", "unique device identifier", "udi-di"],
    "serial_number": ["serial number", "serial no", "serial #", "s/n", "sn"],
    "department": ["department", "dept", "unit", "ward"],
    "location": ["location", "room", "site", "building"],
    "purchase_date": ["purchase date", "date purchased", "acquisition date", "install date"],
    "status": ["status", "condition", "operational status"],
}

FUZZY_HEADER_THRESHOLD = 80


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


# Flattened lookup: normalized synonym -> canonical field
_NORMALIZED_LOOKUP: dict[str, str] = {}
for canonical, synonyms in _ALIASES.items():
    for syn in synonyms + [canonical.replace("_", " ")]:
        _NORMALIZED_LOOKUP[_normalize(syn)] = canonical


@dataclass
class ColumnMapping:
    """Result of mapping a spreadsheet's headers onto canonical fields."""

    field_to_column: dict[str, str]     # canonical field -> original column name
    unmapped_columns: list[str]         # original columns not mapped to anything


def map_columns(columns: list[str]) -> ColumnMapping:
    """Map raw spreadsheet headers onto canonical `InventoryItem` fields."""
    field_to_column: dict[str, str] = {}
    remaining = list(columns)

    # Pass 1: exact (normalized) match.
    still_remaining = []
    for col in remaining:
        canonical = _NORMALIZED_LOOKUP.get(_normalize(col))
        if canonical and canonical not in field_to_column:
            field_to_column[canonical] = col
        else:
            still_remaining.append(col)
    remaining = still_remaining

    # Pass 2: fuzzy match any leftovers against the synonym table.
    synonym_keys = list(_NORMALIZED_LOOKUP.keys())
    still_remaining = []
    for col in remaining:
        match = process.extractOne(
            _normalize(col), synonym_keys, scorer=fuzz.WRatio, score_cutoff=FUZZY_HEADER_THRESHOLD
        )
        if match:
            canonical = _NORMALIZED_LOOKUP[match[0]]
            if canonical not in field_to_column:
                field_to_column[canonical] = col
                continue
        still_remaining.append(col)

    return ColumnMapping(field_to_column=field_to_column, unmapped_columns=still_remaining)


def validate_mapping(mapping: ColumnMapping) -> None:
    missing = [f for f in REQUIRED_FIELDS if f not in mapping.field_to_column]
    if missing:
        raise MissingColumnsError(missing)
