"""Equipment Master import adapter -- Roadmap PR20C (Parse + Normalize +
Validate only).

Authoritative design: `docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md`
§6.3 (adapter shape), §7 (source workbook contract), §8 (32-column field
mapping), §9 OD-1/OD-2/OD-3/OD-4 (Owner Decisions, all RESOLVED), all
merged via GitHub PR #92 (squash SHA
120319afb44f12340790a74dfaf53fa5068591ee). Do not restate the rationale
here -- read the design doc for it. This module implements exactly that
contract.

**Scope boundary (§9 OD-2, strictly enforced by this module's shape):**
this adapter classifies each row (structurally sound / CREATE candidate /
UPDATE candidate / conflict) via `ValidationFinding` rows only. It never
mutates `equipment` -- `plan_dry_run`/`execute` are intentionally left at
the base `ImportAdapter` class's `NotImplementedError` default (§24:
PR20D/PR20E's own scope, not this module's).

**OD-4 (never fabricate `asset_number`):** the current 32-column
`export_template.xlsx` contract supplies no `asset_number` source. Every
row that would otherwise be a potential CREATE candidate therefore always
receives the blocking `ASSET_NUMBER_REQUIRED_FOR_CREATE` finding (§9
OD-4) -- this is the correct, designed behavior, not a bug: parser/
validation readiness (this module) is deliberately distinct from
CREATE-execution readiness (blocked until the Repository Owner supplies
an authoritative Asset Number source).
"""

from __future__ import annotations

import io
import math
import zipfile
from dataclasses import dataclass, field
from typing import Any

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidInputError
from app.crud import equipment as equipment_crud
from app.models.equipment import Equipment, EquipmentStatus
from app.services.identifiers import normalize_bcm_code, normalize_item_no
from app.services.import_adapter import (
    MAX_IMPORT_ROWS,
    DryRunPlan,
    FieldError,
    ImportAdapter,
    RawImportRecord,
    register_adapter,
)
from app.services.import_service import (
    MAX_HEADER_COLUMNS,
    MAX_UPLOAD_BYTES,
    MAX_WORKSHEET_COUNT,
    _validate_zip_archive_bounds,
)
from app.services.import_source_reader import VerifiedSourceContent

DATASET_TYPE = "equipment_master"

# ---------------------------------------------------------------------------
# §7/§9 OD-1: the authoritative worksheet/header contract, verbatim from the
# Owner-supplied export_template.xlsx evidence. A closed-world list -- the
# parser must not invent, assume, or accept a column beyond this set.
# ---------------------------------------------------------------------------
WORKSHEET_NAME = "Sheet1"

# Header text -> internal role. Every key below must be present in row 1
# exactly once (§7's required-structural-columns rule); a role of `None`
# means the column is intentionally-ignored/deferred (§8) -- its header
# presence is still governed, but no per-row cell value is ever extracted
# for it, since "PR20C must not depend on a deferred field" (§8).
_GOVERNED_HEADERS: dict[str, str | None] = {
    "Item No.": "item_no",
    "ID CODE": "bcm_code",
    "Asset ID": "asset_id",
    "ปีที่ซื้อ": None,
    "วันที่ลงทะเบียน": None,
    "วันที่รับ": None,
    "วันเริ่มประกัน": None,
    "วันหมดประกัน": None,
    "ชื่อไทย": "equipment_name",
    "ชื่ออังกฤษ": None,
    "Ownership": None,
    "กลุ่มโรงพยาบาล": None,
    "โรงพยาบาล": None,
    "หน่วยงาน": None,
    "อาคาร": None,
    "ชั้น": None,
    "ห้อง": None,
    "ประเภทเครื่องมือ": None,
    "ชนิดเครื่องมือ": None,
    "ยี่ห้อ": "brand",
    "รุ่น": "model",
    "S/N": "serial_number",
    "ราคาซื้อ": None,
    "ผู้ขาย": None,
    "ชื่อผู้ติดต่อ": None,
    "เบอร์โทรผู้ติดต่อ": None,
    "สถานะเครื่องมือ": "status",
    "อยู่ในประกัน": None,
    "Life Expect": None,
    "ความเสี่ยง": None,
    "Classification": None,
    "TOR": None,
}
assert len(_GOVERNED_HEADERS) == 32  # §9 OD-1: exactly 32 governed columns

# §8: Equipment column widths this adapter must bound against, matching
# `backend/app/models/equipment.py` exactly -- so an overlength value is
# always a reported finding, never left to fail only once a later slice
# actually attempts the write.
_FIELD_MAX_LENGTHS: dict[str, int] = {
    "asset_id": 100,
    "equipment_name": 255,
    "brand": 100,
    "model": 100,
    "serial_number": 100,
}

# §10: illustrative legacy-status mapping, matching PR12's own
# ASSET_STATUS_MAPPING precedent -- pending confirmation against the real
# 4,729-row source content (§9 OD-1's own note: "the exact per-value Thai/
# English string enumeration remains an implementation-time task for
# PR20C's own PR ... not a further Owner Decision, because the fallback
# behavior ... is already fixed"). Keys are lowercased/trimmed for
# case-insensitive exact-match lookup; any value not listed here is
# unmappable by design -- a blocking finding, never a guess.
STATUS_MAPPING: dict[str, EquipmentStatus] = {
    "active": EquipmentStatus.AVAILABLE_AT_POOL,
    "available": EquipmentStatus.AVAILABLE_AT_POOL,
    "พร้อมใช้งาน": EquipmentStatus.AVAILABLE_AT_POOL,
    "defective": EquipmentStatus.UNAVAILABLE_DEFECTIVE,
    "faulty": EquipmentStatus.UNAVAILABLE_DEFECTIVE,
    "broken": EquipmentStatus.UNAVAILABLE_DEFECTIVE,
    "ชำรุด": EquipmentStatus.UNAVAILABLE_DEFECTIVE,
    "decommissioned": EquipmentStatus.DECOMMISSIONED,
    "disposed": EquipmentStatus.DECOMMISSIONED,
    "written off": EquipmentStatus.DECOMMISSIONED,
    "จำหน่าย": EquipmentStatus.DECOMMISSIONED,
    # ISSUED_TO_WARD is intentionally absent -- §9 OD-2's Legacy Lifecycle
    # Policy: PR20 never initializes a CREATE candidate directly into
    # ISSUED_TO_WARD (no synthetic BorrowTransaction), so no legacy status
    # string maps to it here; a legacy value that appears to mean
    # "currently issued" is unmappable-by-design and falls through to the
    # blocking STATUS_UNMAPPABLE finding below, per §11.
}

# ---------------------------------------------------------------------------
# §12: centralized, stable finding codes. `ASSET_NUMBER_REQUIRED_FOR_CREATE`
# is used verbatim as specified by §9 OD-4 -- every other code follows this
# module's own `EQUIPMENT_MASTER_<CONDITION>` convention (§12's own
# illustrative naming), since no exact code beyond the OD-4 one is fixed by
# the merged design.
# ---------------------------------------------------------------------------
CODE_BCM_MISSING = "EQUIPMENT_MASTER_BCM_MISSING"
CODE_BCM_INVALID = "EQUIPMENT_MASTER_BCM_INVALID"
CODE_BCM_DUPLICATE_IN_SOURCE = "EQUIPMENT_MASTER_BCM_DUPLICATE_IN_SOURCE"
CODE_ITEM_NO_MISSING = "EQUIPMENT_MASTER_ITEM_NO_MISSING"
CODE_ITEM_NO_INVALID = "EQUIPMENT_MASTER_ITEM_NO_INVALID"
CODE_ITEM_NO_DUPLICATE_IN_SOURCE = "EQUIPMENT_MASTER_ITEM_NO_DUPLICATE_IN_SOURCE"
CODE_IDENTITY_CONFLICT = "EQUIPMENT_MASTER_IDENTITY_CONFLICT"
CODE_EQUIPMENT_NAME_MISSING = "EQUIPMENT_MASTER_EQUIPMENT_NAME_MISSING"
CODE_FIELD_TOO_LONG = "EQUIPMENT_MASTER_FIELD_TOO_LONG"
CODE_SERIAL_NUMBER_CONFLICT = "EQUIPMENT_MASTER_SERIAL_NUMBER_CONFLICT"
CODE_ASSET_ID_CONFLICT = "EQUIPMENT_MASTER_ASSET_ID_CONFLICT"
CODE_STATUS_MISSING = "EQUIPMENT_MASTER_STATUS_MISSING"
CODE_STATUS_UNMAPPABLE = "EQUIPMENT_MASTER_STATUS_UNMAPPABLE"
CODE_STATUS_MISMATCH = "EQUIPMENT_MASTER_STATUS_MISMATCH"
# §9 OD-4: this exact code is the merged design's own stable identifier --
# not prefixed with this module's own convention, since OD-4 names it
# directly.
CODE_ASSET_NUMBER_REQUIRED_FOR_CREATE = "ASSET_NUMBER_REQUIRED_FOR_CREATE"


# ---------------------------------------------------------------------------
# §7: cell-level extraction for the two governed identifiers. Distinct
# acceptance rules per §7/§9 OD-1's identifier cell contract: BCM (`ID
# CODE`) is text-only; Item Number (`Item No.`) accepts text or a
# losslessly-convertible integer-numeric cell. Blank vs. invalid-but-present
# are reported as distinct outcomes, on purpose -- both currently prevent
# CREATE/UPDATE (§9 OD-3's blank/null matrix), but a distinct code is more
# diagnostically useful and does not itself change OD-3's blocking policy.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _CellResult:
    outcome: str  # "blank" | "valid" | "invalid"
    value: str | None = None
    detail: str | None = None


def _extract_bcm_cell(value: object) -> _CellResult:
    if value is None:
        return _CellResult("blank")
    if isinstance(value, str):
        text = value.strip()
        return _CellResult("blank") if not text else _CellResult("valid", value=text)
    # §7: BCM (`ID CODE`) accepts a text-typed cell only -- any numeric-typed
    # (including bool, a numeric subtype) or other non-text cell is a
    # blocking ERROR, never silently coerced to text.
    return _CellResult("invalid", detail="ID CODE must be a text cell, not a numeric cell.")


def _extract_item_no_cell(value: object) -> _CellResult:
    if value is None:
        return _CellResult("blank")
    if isinstance(value, str):
        text = value.strip()
        return _CellResult("blank") if not text else _CellResult("valid", value=text)
    if isinstance(value, bool):
        return _CellResult("invalid", detail="Item No. must not be a boolean-typed cell.")
    if isinstance(value, int):
        # §7: converted losslessly to its canonical decimal string
        # representation -- never scientific notation, never a
        # floating-point artifact. No leading zero is ever reconstructed
        # (§7's PR92-H1R correction): this is the observed value only.
        return _CellResult("valid", value=str(value))
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return _CellResult("invalid", detail="Item No. numeric cell is not a finite number.")
        if not value.is_integer():
            return _CellResult("invalid", detail="Item No. numeric cell must be a whole number.")
        return _CellResult("valid", value=str(int(value)))
    return _CellResult("invalid", detail="Item No. cell has an unsupported type.")


def _cell_text(value: object) -> str | None:
    """Trim-only extraction for a governed non-identifier text column
    (§8's general cell-normalization rule: "trim whitespace; an empty
    string normalizes to null"). Never applied to BCM/Item No, which have
    their own distinct cell-type rules above."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)
    return str(value).strip() or None


# ---------------------------------------------------------------------------
# §7: workbook/worksheet/header structural parsing (synchronous, CPU-bound
# -- always invoked via the framework's own `asyncio.to_thread`, never
# directly, per `import_validation_service.run_validation`).
# ---------------------------------------------------------------------------


def _reject_macro_parts(content: bytes) -> None:
    """§21: "Never execute workbook formulas or macros." The shared PR12
    `_validate_zip_archive_bounds` bounds the archive's *shape* (entry
    count/size/ratio, allowed top-level paths) but its `xl/` prefix
    allowlist does not itself distinguish an ordinary `.xlsx` from a
    macro-enabled workbook smuggled in under an `.xlsx` filename/content-
    type -- `xl/vbaProject.bin` (and its optional digital-signature
    sibling) is a legitimate path under `xl/`. Never merely relying on
    "openpyxl doesn't execute it" is insufficient defense-in-depth for
    hostile input (§21): any such part is rejected outright, before
    `load_workbook` ever touches the archive."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = archive.namelist()
    except zipfile.BadZipFile as exc:
        raise InvalidInputError(
            "The uploaded file could not be read as a valid Excel (.xlsx) spreadsheet."
        ) from exc
    for name in names:
        normalized = name.replace("\\", "/").lower()
        if "vbaproject" in normalized:
            raise InvalidInputError(
                "The uploaded file contains a macro-enabled component (VBA project) and cannot "
                "be accepted as a plain Excel (.xlsx) spreadsheet."
            )


def _load_sheet1(content: bytes) -> Worksheet:
    _validate_zip_archive_bounds(content)
    _reject_macro_parts(content)
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise InvalidInputError(
            "The uploaded file could not be read as a valid Excel (.xlsx) spreadsheet."
        ) from exc
    if len(workbook.sheetnames) > MAX_WORKSHEET_COUNT:
        raise InvalidInputError(
            f"The uploaded file contains more than {MAX_WORKSHEET_COUNT} worksheets, "
            "exceeding what a normal Equipment Master export contains."
        )
    # §7: the parser MUST select `Sheet1` by name -- never `workbook.active`
    # (an arbitrary first/default worksheet). Any other worksheet present
    # is ignored, not interpreted, per the V1 contract.
    if WORKSHEET_NAME not in workbook.sheetnames:
        raise InvalidInputError(
            f"The uploaded file has no worksheet named '{WORKSHEET_NAME}'. "
            "Equipment Master import requires the authoritative worksheet to be present by name."
        )
    return workbook[WORKSHEET_NAME]


def _validate_headers(worksheet: Worksheet) -> dict[str, int]:
    """§7: header is exactly row 1; column order is not authoritative
    (exact-header-name based). All 32 governed headers must be present
    exactly once; missing/duplicate/unknown-extra are each a structural
    `ERROR` (fail-closed on schema drift, §7)."""
    header_row = next(worksheet.iter_rows(min_row=1, max_row=1, values_only=True), None)
    if header_row is None:
        raise InvalidInputError("The uploaded spreadsheet is empty; no header row was found.")
    if len(header_row) > MAX_HEADER_COLUMNS:
        raise InvalidInputError(
            f"The uploaded file's header row contains more than {MAX_HEADER_COLUMNS} columns, "
            "exceeding what a normal Equipment Master export contains."
        )

    seen: dict[str, list[int]] = {}
    for idx, raw in enumerate(header_row):
        text = _cell_text(raw)
        if text is None:
            continue
        seen.setdefault(text, []).append(idx)

    missing = [header for header in _GOVERNED_HEADERS if header not in seen]
    if missing:
        raise InvalidInputError(
            "The uploaded spreadsheet is missing required column(s): " + ", ".join(missing)
        )
    duplicated = [header for header, idxs in seen.items() if header in _GOVERNED_HEADERS and len(idxs) > 1]
    if duplicated:
        raise InvalidInputError(
            "The uploaded spreadsheet has duplicate column(s): " + ", ".join(sorted(duplicated))
        )
    unknown = sorted(header for header in seen if header not in _GOVERNED_HEADERS)
    if unknown:
        raise InvalidInputError(
            "The uploaded spreadsheet contains unrecognized column(s) not part of the approved "
            "Equipment Master schema: " + ", ".join(unknown)
        )

    return {header: seen[header][0] for header in _GOVERNED_HEADERS}


def _parse_rows(worksheet: Worksheet, header_index: dict[str, int]) -> list[RawImportRecord]:
    def cell_at(values: tuple, header: str) -> object:
        idx = header_index[header]
        return values[idx] if idx < len(values) else None

    # §7's closed-world header contract must also bind the data rows, not
    # merely row 1: `_validate_headers` only inspects non-blank header
    # cells, so a column whose row-1 cell is blank (no name at all) is
    # invisible to that check and would otherwise let data smuggle through
    # a column outside the approved 32-column schema. Any non-blank cell
    # at a column index that isn't one of the 32 governed indices is
    # therefore rejected here, structurally, the first time it's seen.
    known_indices = set(header_index.values())

    records: list[RawImportRecord] = []
    for row_number, values in enumerate(worksheet.iter_rows(min_row=2, values_only=True), start=2):
        if values is None or all(_cell_text(v) is None for v in values):
            continue  # §7: blank rows skipped, not counted toward total_rows
        for idx, value in enumerate(values):
            if idx not in known_indices and _cell_text(value) is not None:
                raise InvalidInputError(
                    f"Row {row_number} contains data in a column outside the approved Equipment "
                    "Master schema (an unnamed/extra column is not permitted)."
                )
        if len(records) >= MAX_IMPORT_ROWS:
            raise InvalidInputError(
                f"The uploaded file contains more than {MAX_IMPORT_ROWS} data rows, "
                "exceeding the maximum a single import batch may contain."
            )
        records.append(
            RawImportRecord(
                row_number=row_number,
                fields={
                    "bcm": _extract_bcm_cell(cell_at(values, "ID CODE")),
                    "item_no": _extract_item_no_cell(cell_at(values, "Item No.")),
                    "asset_id": _cell_text(cell_at(values, "Asset ID")),
                    "equipment_name": _cell_text(cell_at(values, "ชื่อไทย")),
                    "brand": _cell_text(cell_at(values, "ยี่ห้อ")),
                    "model": _cell_text(cell_at(values, "รุ่น")),
                    "serial_number": _cell_text(cell_at(values, "S/N")),
                    "status": _cell_text(cell_at(values, "สถานะเครื่องมือ")),
                },
            )
        )
    return records


def _parse_workbook_sync(content: bytes) -> list[RawImportRecord]:
    """Everything CPU-bound about turning verified source bytes into
    typed records, run as one unit via the framework's own
    `asyncio.to_thread(adapter.parse, raw_input)` (never a second,
    adapter-owned concurrency mechanism, §10.1)."""
    worksheet = _load_sheet1(content)
    header_index = _validate_headers(worksheet)
    return _parse_rows(worksheet, header_index)


# ---------------------------------------------------------------------------
# §6.3/§13: bulk business context -- exactly two-to-four `IN(...)` queries
# for the whole batch (never one query per row), plus in-workbook duplicate
# detection (§9 OD-3 cases 6/7, §13(B)/(C)).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EquipmentMasterContext:
    existing_by_bcm: dict[str, Equipment] = field(default_factory=dict)
    existing_by_item_no: dict[str, Equipment] = field(default_factory=dict)
    existing_by_serial: dict[str, Equipment] = field(default_factory=dict)
    existing_by_asset_id: dict[str, Equipment] = field(default_factory=dict)
    duplicate_bcm_rows: frozenset[int] = frozenset()
    duplicate_item_no_rows: frozenset[int] = frozenset()


def _rows_with_duplicate_values(values_by_row: dict[int, str]) -> frozenset[int]:
    """§9 OD-3 cases 6/7, §13: ALL rows sharing a duplicated value are
    flagged -- never merely the second occurrence, never "last row wins"."""
    seen: dict[str, list[int]] = {}
    for row_number, value in values_by_row.items():
        seen.setdefault(value, []).append(row_number)
    duplicated: set[int] = set()
    for rows in seen.values():
        if len(rows) > 1:
            duplicated.update(rows)
    return frozenset(duplicated)


class EquipmentMasterAdapter(ImportAdapter):
    """Roadmap PR20C. Implements `parse`/`preload_business_context`/
    `validate_business_rules` only -- `plan_dry_run`/`execute` are left at
    the base class's `NotImplementedError` default (§9 OD-2's scope
    boundary; those belong to PR20D/PR20E)."""

    dataset_type = DATASET_TYPE
    ruleset_version = "1"

    def parse(self, raw_input: Any) -> list[RawImportRecord]:
        # §6.5: `raw_input` is always a checksum/length-verified
        # `VerifiedSourceContent` for this adapter -- PR20A's framework
        # code (never this adapter) resolves and hands it in, since
        # `equipment_master` always uses the byte-storage upload path
        # (§6.2's registration-endpoint guard rejects the metadata-only
        # path for this dataset_type before this adapter is ever reached).
        if not isinstance(raw_input, VerifiedSourceContent):
            raise InvalidInputError(
                "Equipment Master import requires a verified, byte-backed source; "
                "none was supplied for this session."
            )
        content = raw_input.content
        if len(content) > MAX_UPLOAD_BYTES:
            raise InvalidInputError(
                f"Stored source content exceeds the maximum allowed size of "
                f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
            )
        return _parse_workbook_sync(content)

    async def preload_business_context(
        self, db: AsyncSession, records: list[RawImportRecord]
    ) -> EquipmentMasterContext:
        bcm_values: dict[int, str] = {}
        item_no_values: dict[int, str] = {}
        for record in records:
            bcm_cell: _CellResult = record.fields["bcm"]
            if bcm_cell.outcome == "valid":
                bcm_values[record.row_number] = bcm_cell.value  # type: ignore[assignment]
            item_no_cell: _CellResult = record.fields["item_no"]
            if item_no_cell.outcome == "valid":
                item_no_values[record.row_number] = item_no_cell.value  # type: ignore[assignment]

        # §9 OD-3's blank/null matrix and identity matrix both operate on
        # the *normalized* form (ADR-002 canonicalization) -- normalize
        # here, once, rather than duplicating this in validate_business_rules.
        normalized_bcm: dict[int, str] = {}
        for row_number, raw in bcm_values.items():
            try:
                normalized_bcm[row_number] = normalize_bcm_code(raw)
            except InvalidInputError:
                continue  # re-validated (and reported) in validate_business_rules
        normalized_item_no: dict[int, str] = {}
        for row_number, raw in item_no_values.items():
            try:
                normalized_item_no[row_number] = normalize_item_no(raw)
            except InvalidInputError:
                continue

        duplicate_bcm_rows = _rows_with_duplicate_values(normalized_bcm)
        duplicate_item_no_rows = _rows_with_duplicate_values(normalized_item_no)

        bcm_codes_to_check = set(normalized_bcm.values())
        item_nos_to_check = set(normalized_item_no.values())
        serials_to_check = {
            record.fields["serial_number"] for record in records if record.fields["serial_number"]
        }
        asset_ids_to_check = {
            record.fields["asset_id"] for record in records if record.fields["asset_id"]
        }

        existing_by_bcm = await equipment_crud.get_by_bcm_codes(db, list(bcm_codes_to_check))
        existing_by_item_no = await equipment_crud.get_by_item_nos(db, list(item_nos_to_check))
        existing_by_serial = await equipment_crud.get_by_serial_numbers(db, list(serials_to_check))
        existing_by_asset_id = await equipment_crud.get_by_asset_ids(db, list(asset_ids_to_check))

        # Stash the normalized values back so validate_business_rules never
        # re-derives them (single source of truth for what "normalized"
        # means for this batch).
        for record in records:
            row_number = record.row_number
            record.fields["bcm_normalized"] = normalized_bcm.get(row_number)
            record.fields["item_no_normalized"] = normalized_item_no.get(row_number)

        return EquipmentMasterContext(
            existing_by_bcm=existing_by_bcm,
            existing_by_item_no=existing_by_item_no,
            existing_by_serial=existing_by_serial,
            existing_by_asset_id=existing_by_asset_id,
            duplicate_bcm_rows=duplicate_bcm_rows,
            duplicate_item_no_rows=duplicate_item_no_rows,
        )

    def validate_business_rules(
        self, record: RawImportRecord, context: object
    ) -> list[FieldError]:
        assert isinstance(context, EquipmentMasterContext)
        findings: list[FieldError] = []

        bcm_cell: _CellResult = record.fields["bcm"]
        item_no_cell: _CellResult = record.fields["item_no"]

        # §9 OD-3: BCM cell-type/blank checks.
        bcm_blocking = False
        if bcm_cell.outcome == "blank":
            findings.append(
                FieldError(field="bcm_code", error_code=CODE_BCM_MISSING, message="ID CODE is required.")
            )
            bcm_blocking = True
        elif bcm_cell.outcome == "invalid":
            findings.append(
                FieldError(field="bcm_code", error_code=CODE_BCM_INVALID, message=bcm_cell.detail or "Invalid ID CODE.")
            )
            bcm_blocking = True
        else:
            normalized_bcm = record.fields.get("bcm_normalized")
            if normalized_bcm is None:
                # Failed normalize_bcm_code() in preload_business_context.
                try:
                    normalize_bcm_code(bcm_cell.value)  # re-raise for the message
                except InvalidInputError as exc:
                    findings.append(
                        FieldError(field="bcm_code", error_code=CODE_BCM_INVALID, message=f"Invalid ID CODE: {exc.message}")
                    )
                bcm_blocking = True
            elif record.row_number in context.duplicate_bcm_rows:
                findings.append(
                    FieldError(
                        field="bcm_code",
                        error_code=CODE_BCM_DUPLICATE_IN_SOURCE,
                        message=f"ID CODE '{normalized_bcm}' appears on more than one row in this workbook.",
                    )
                )
                bcm_blocking = True

        # §9 OD-3: Item Number cell-type/blank checks.
        item_no_blocking = False
        if item_no_cell.outcome == "blank":
            findings.append(
                FieldError(field="item_no", error_code=CODE_ITEM_NO_MISSING, message="Item No. is required.")
            )
            item_no_blocking = True
        elif item_no_cell.outcome == "invalid":
            findings.append(
                FieldError(
                    field="item_no", error_code=CODE_ITEM_NO_INVALID, message=item_no_cell.detail or "Invalid Item No."
                )
            )
            item_no_blocking = True
        else:
            normalized_item_no = record.fields.get("item_no_normalized")
            if normalized_item_no is None:
                try:
                    normalize_item_no(item_no_cell.value)
                except InvalidInputError as exc:
                    findings.append(
                        FieldError(
                            field="item_no", error_code=CODE_ITEM_NO_INVALID, message=f"Invalid Item No.: {exc.message}"
                        )
                    )
                item_no_blocking = True
            elif record.row_number in context.duplicate_item_no_rows:
                findings.append(
                    FieldError(
                        field="item_no",
                        error_code=CODE_ITEM_NO_DUPLICATE_IN_SOURCE,
                        message=f"Item No. '{normalized_item_no}' appears on more than one row in this workbook.",
                    )
                )
                item_no_blocking = True

        # §9 OD-3: "The blank/null cases above are mandatory preconditions"
        # -- evaluated before the identity matrix; a row failing either
        # never reaches identity resolution, and no fallback/derived
        # identifier is ever substituted.
        if bcm_blocking or item_no_blocking:
            return findings

        bcm = record.fields["bcm_normalized"]
        item_no = record.fields["item_no_normalized"]
        equip_by_bcm = context.existing_by_bcm.get(bcm)
        equip_by_item_no = context.existing_by_item_no.get(item_no)

        if equip_by_bcm is None and equip_by_item_no is None:
            # §9 OD-3 case 1: CREATE candidate.
            findings.extend(self._validate_create_candidate(record, context))
        elif equip_by_bcm is not None and equip_by_item_no is not None and equip_by_bcm.id == equip_by_item_no.id:
            # §9 OD-3 case 2: UPDATE candidate.
            findings.extend(self._validate_update_candidate(record, context, equip_by_bcm))
        else:
            # §9 OD-3 cases 3/4/5: every remaining combination is a
            # blocking cross-identity conflict -- never auto-replace,
            # never auto-choose, never create a duplicate logical
            # Equipment.
            findings.append(
                FieldError(
                    field=None,
                    error_code=CODE_IDENTITY_CONFLICT,
                    message=(
                        f"BCM '{bcm}' and Item No. '{item_no}' do not consistently identify the same "
                        "existing Equipment record (or the same new record)."
                    ),
                )
            )

        return findings

    def _validate_create_candidate(
        self, record: RawImportRecord, context: EquipmentMasterContext
    ) -> list[FieldError]:
        findings: list[FieldError] = []

        equipment_name = record.fields["equipment_name"]
        if equipment_name is None:
            findings.append(
                FieldError(
                    field="equipment_name",
                    error_code=CODE_EQUIPMENT_NAME_MISSING,
                    message="ชื่อไทย (Thai name) is required to create a new Equipment record.",
                )
            )
        else:
            findings.extend(self._length_findings({"equipment_name": equipment_name}))

        findings.extend(
            self._length_findings(
                {
                    key: record.fields[key]
                    for key in ("asset_id", "brand", "model", "serial_number")
                    if record.fields[key] is not None
                }
            )
        )

        serial_number = record.fields["serial_number"]
        if serial_number is not None and serial_number in context.existing_by_serial:
            # Unlike the UPDATE case, a CREATE candidate has no "self" record
            # to exempt -- any existing match is a blocking conflict, since
            # Equipment.serial_number is DB-unique.
            findings.append(
                FieldError(
                    field="serial_number",
                    error_code=CODE_SERIAL_NUMBER_CONFLICT,
                    message="S/N already belongs to an existing Equipment record.",
                )
            )

        status_raw = record.fields["status"]
        if status_raw is None:
            findings.append(
                FieldError(
                    field="status",
                    error_code=CODE_STATUS_MISSING,
                    message="สถานะเครื่องมือ (equipment status) is required to create a new Equipment record.",
                )
            )
        elif status_raw.strip().lower() not in STATUS_MAPPING:
            findings.append(
                FieldError(
                    field="status",
                    error_code=CODE_STATUS_UNMAPPABLE,
                    message=f"Unrecognized equipment status value: '{status_raw}'.",
                )
            )

        # §9 OD-4: every potential CREATE candidate is blocked -- the
        # currently-approved 32-column contract supplies no authoritative
        # asset_number source. This finding is unconditional for every
        # CREATE candidate, by design.
        findings.append(
            FieldError(
                field="asset_number",
                error_code=CODE_ASSET_NUMBER_REQUIRED_FOR_CREATE,
                message=(
                    "An authoritative Asset Number source is required to create a new Equipment "
                    "record; none is available in the current Equipment Master workbook contract. "
                    "This row cannot become executable CREATE work until the Repository Owner "
                    "supplies one (Roadmap PR20 §9 OD-4)."
                ),
            )
        )

        return findings

    def _validate_update_candidate(
        self, record: RawImportRecord, context: EquipmentMasterContext, target: Equipment
    ) -> list[FieldError]:
        findings: list[FieldError] = []

        findings.extend(
            self._length_findings(
                {
                    key: record.fields[key]
                    for key in ("asset_id", "equipment_name", "brand", "model", "serial_number")
                    if record.fields[key] is not None
                }
            )
        )

        serial_number = record.fields["serial_number"]
        if serial_number is not None:
            other = context.existing_by_serial.get(serial_number)
            if other is not None and other.id != target.id:
                findings.append(
                    FieldError(
                        field="serial_number",
                        error_code=CODE_SERIAL_NUMBER_CONFLICT,
                        message="S/N already belongs to a different Equipment record.",
                    )
                )

        asset_id = record.fields["asset_id"]
        if asset_id is not None:
            other = context.existing_by_asset_id.get(asset_id)
            if other is not None and other.id != target.id:
                findings.append(
                    FieldError(
                        field="asset_id",
                        error_code=CODE_ASSET_ID_CONFLICT,
                        message="Asset ID already belongs to a different Equipment record.",
                        severity="warning",
                    )
                )

        # §9 OD-2 Legacy Lifecycle Policy / §10: legacy status is read for
        # cross-check only -- never applied to the existing record's live
        # status. §10 states the unmappable-status fallback generally ("any
        # legacy status this design cannot safely map produces a blocking
        # ERROR"), not only for CREATE -- a non-blank UPDATE-row status
        # value that fails to map to one of the four states is therefore
        # the same blocking CODE_STATUS_UNMAPPABLE as a CREATE candidate's,
        # never silently ignored. A *mapped* value that simply differs from
        # the live status is a separate, non-blocking WARNING only (§8's
        # UPDATE column: "never overwrites current live status").
        status_raw = record.fields["status"]
        if status_raw is not None:
            mapped = STATUS_MAPPING.get(status_raw.strip().lower())
            if mapped is None:
                findings.append(
                    FieldError(
                        field="status",
                        error_code=CODE_STATUS_UNMAPPABLE,
                        message=f"Unrecognized equipment status value: '{status_raw}'.",
                    )
                )
            elif mapped != target.status:
                findings.append(
                    FieldError(
                        field="status",
                        error_code=CODE_STATUS_MISMATCH,
                        message=(
                            f"Legacy status '{status_raw}' maps to '{mapped.value}', which differs from "
                            f"the current live status '{target.status.value}'. Not applied -- current "
                            "operational status remains authoritative."
                        ),
                        severity="warning",
                    )
                )

        return findings

    @staticmethod
    def _length_findings(values: dict[str, str]) -> list[FieldError]:
        findings: list[FieldError] = []
        for key, value in values.items():
            max_length = _FIELD_MAX_LENGTHS[key]
            if len(value) > max_length:
                findings.append(
                    FieldError(
                        field=key,
                        error_code=CODE_FIELD_TOO_LONG,
                        message=f"{key} exceeds the maximum length of {max_length} characters.",
                    )
                )
        return findings

    # plan_dry_run / execute: intentionally not overridden (§9 OD-2's scope
    # boundary; base ImportAdapter's NotImplementedError default applies).


register_adapter(EquipmentMasterAdapter())
