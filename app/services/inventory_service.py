"""Hospital inventory import + persistence (FUNCTION 3)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from app.database.db import Database
from app.models.inventory import InventoryItem
from app.utils.excel_mapper import ColumnMapping, map_columns, validate_mapping
from app.utils.exceptions import InvalidExcelFileError
from app.utils.logging_config import get_audit_logger, get_logger
from app.utils.validators import normalize_text, validate_excel_path

logger = get_logger(__name__)
audit_import = get_audit_logger("import")


@dataclass
class ImportResult:
    total_rows: int
    imported: int
    updated: int
    skipped: int
    mapping: ColumnMapping
    warnings: list[str]


def _parse_purchase_date(value) -> Optional[date]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.date()
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat"}:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


class InventoryService:
    def __init__(self, db: Database):
        self.db = db

    def import_excel(self, path: str | Path) -> ImportResult:
        """Import a hospital inventory spreadsheet (.xlsx / .xls) into SQLite."""
        validated_path = validate_excel_path(path)
        try:
            engine = "openpyxl" if validated_path.suffix.lower() == ".xlsx" else "xlrd"
            df = pd.read_excel(validated_path, engine=engine, dtype=str)
        except Exception as exc:
            raise InvalidExcelFileError(f"Could not read Excel file: {exc}") from exc

        if df.empty:
            raise InvalidExcelFileError("The spreadsheet has no data rows.")

        df.columns = [str(c).strip() for c in df.columns]
        mapping = map_columns(list(df.columns))
        validate_mapping(mapping)

        warnings = []
        if mapping.unmapped_columns:
            warnings.append(
                f"{len(mapping.unmapped_columns)} column(s) could not be auto-mapped and were "
                f"kept as extra fields: {', '.join(mapping.unmapped_columns)}"
            )

        imported = 0
        updated = 0
        skipped = 0

        for _, row in df.iterrows():
            item = self._row_to_item(row, mapping)
            if not item.asset_number:
                skipped += 1
                continue
            existing = self.db.query_one(
                "SELECT id FROM inventory_items WHERE asset_number = ?", (item.asset_number,)
            )
            if existing:
                self._update(item, existing["id"])
                updated += 1
            else:
                self._insert(item)
                imported += 1

        result = ImportResult(
            total_rows=len(df),
            imported=imported,
            updated=updated,
            skipped=skipped,
            mapping=mapping,
            warnings=warnings,
        )
        audit_import.info(
            "Inventory import from %s: %d imported, %d updated, %d skipped (of %d rows)",
            validated_path,
            imported,
            updated,
            skipped,
            len(df),
        )
        return result

    @staticmethod
    def _row_to_item(row: pd.Series, mapping: ColumnMapping) -> InventoryItem:
        def get(field: str) -> str:
            col = mapping.field_to_column.get(field)
            return normalize_text(row[col]) if col else ""

        extra_fields = {col: normalize_text(row[col]) for col in mapping.unmapped_columns}

        return InventoryItem(
            asset_number=get("asset_number"),
            equipment_code=get("equipment_code"),
            device_name=get("device_name"),
            manufacturer=get("manufacturer"),
            brand=get("brand"),
            model_number=get("model_number"),
            catalog_number=get("catalog_number"),
            udi=get("udi"),
            serial_number=get("serial_number"),
            department=get("department"),
            location=get("location"),
            purchase_date=_parse_purchase_date(row[mapping.field_to_column["purchase_date"]])
            if "purchase_date" in mapping.field_to_column
            else None,
            status=get("status"),
            extra_fields=extra_fields,
        )

    def _insert(self, item: InventoryItem) -> int:
        cur = self.db.execute(
            """
            INSERT INTO inventory_items (
                asset_number, equipment_code, device_name, manufacturer, brand, model_number,
                catalog_number, udi, serial_number, department, location, purchase_date,
                status, extra_fields, imported_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                item.asset_number,
                item.equipment_code,
                item.device_name,
                item.manufacturer,
                item.brand,
                item.model_number,
                item.catalog_number,
                item.udi,
                item.serial_number,
                item.department,
                item.location,
                item.purchase_date.isoformat() if item.purchase_date else None,
                item.status,
                json.dumps(item.extra_fields, default=str),
                item.imported_at.isoformat(),
            ),
        )
        return cur.lastrowid

    def _update(self, item: InventoryItem, existing_id: int) -> None:
        self.db.execute(
            """
            UPDATE inventory_items SET
                equipment_code=?, device_name=?, manufacturer=?, brand=?, model_number=?,
                catalog_number=?, udi=?, serial_number=?, department=?, location=?,
                purchase_date=?, status=?, extra_fields=?, imported_at=?
            WHERE id=?
            """,
            (
                item.equipment_code,
                item.device_name,
                item.manufacturer,
                item.brand,
                item.model_number,
                item.catalog_number,
                item.udi,
                item.serial_number,
                item.department,
                item.location,
                item.purchase_date.isoformat() if item.purchase_date else None,
                item.status,
                json.dumps(item.extra_fields, default=str),
                item.imported_at.isoformat(),
                existing_id,
            ),
        )

    def list_all(self) -> list[InventoryItem]:
        rows = self.db.query_all("SELECT * FROM inventory_items ORDER BY asset_number")
        return [_row_to_model(row) for row in rows]

    def count(self) -> int:
        row = self.db.query_one("SELECT COUNT(*) AS c FROM inventory_items")
        return int(row["c"]) if row else 0

    def list_departments(self) -> list[str]:
        rows = self.db.query_all(
            "SELECT DISTINCT department FROM inventory_items WHERE department != '' ORDER BY department"
        )
        return [row["department"] for row in rows]


def _row_to_model(row) -> InventoryItem:
    return InventoryItem(
        id=row["id"],
        asset_number=row["asset_number"],
        equipment_code=row["equipment_code"] or "",
        device_name=row["device_name"] or "",
        manufacturer=row["manufacturer"] or "",
        brand=row["brand"] or "",
        model_number=row["model_number"] or "",
        catalog_number=row["catalog_number"] or "",
        udi=row["udi"] or "",
        serial_number=row["serial_number"] or "",
        department=row["department"] or "",
        location=row["location"] or "",
        purchase_date=date.fromisoformat(row["purchase_date"]) if row["purchase_date"] else None,
        status=row["status"] or "",
        extra_fields=json.loads(row["extra_fields"]) if row["extra_fields"] else {},
        imported_at=datetime.fromisoformat(row["imported_at"]),
    )
