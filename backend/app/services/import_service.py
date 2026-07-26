"""Inventory Import (Roadmap PR12).

See docs/audits/04-consolidated-implementation-plan.md Part D ("PR12 --
Inventory import") and Part F ("Inventory Import Plan", §10) for the full
authoritative design this module implements.

Design summary (do not restate elsewhere -- read the plan for rationale):

  - BCM Code is the sole match key used to decide whether an import row is
    a new equipment record or an update to an existing one. Item No,
    Asset ID, and Serial Number are validated as uniqueness constraints
    against *other* records, never used to look up "is this the same
    equipment" (per the Repository Owner's explicit approved treatment).
  - `process_import` is the single entry point for both preview
    (`commit=False`, read-only, zero database writes including audit
    writes) and commit (`commit=True`, revalidates from the raw uploaded
    file bytes every time -- it never trusts a prior preview result
    supplied by the frontend, since preview and commit are two
    independent calls to this same function).
  - "Update existing" mode only ever touches the approved master-data
    field set (Asset ID, Manufacturer/brand, Model, and the raw
    Location/Receive Date/Register Date/Purchase Year provenance fields
    inside `equipment_metadata`) -- it never writes `status`,
    `legacy_status`, `asset_number`, `item_no`, `serial_number`, or
    `equipment_name` on an existing record (Part F.3).
  - Newly created equipment has no source "Asset Number" column to draw
    from (Part F.1's header list has none) -- per explicit Repository
    Owner decision, `asset_number` is provisionally set to the row's own
    canonical BCM Code (deterministic, already unique, introduces no new
    identifier scheme). Documented as a temporary compatibility policy
    for the current schema, not a new business rule.
  - Unexpected failures during the commit write phase roll back the
    entire batch (no partial commit); expected per-row validation
    failures never reach the write phase at all, so they coexist freely
    with rows that do succeed.
"""

import io
import logging
import uuid
from dataclasses import dataclass
from enum import Enum

from fastapi import Request, UploadFile
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AUDIT_ACTION_IMPORT, AUDIT_ENTITY_EQUIPMENT, record_audit_event
from app.core.exceptions import DomainError, InvalidInputError
from app.crud import equipment as equipment_crud
from app.models.equipment import EquipmentStatus
from app.services.identifiers import normalize_bcm_code, normalize_item_no

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Part F.1 step 2: the confirmed source spreadsheet headers. Matched
# case-insensitively, trimmed -- but the canonical label used in every
# error message and header-index lookup is exactly this text.
# ---------------------------------------------------------------------------
REQUIRED_HEADERS: tuple[str, ...] = (
    "Item No.",
    "ID CODE",
    "Asset ID",
    "Equipment Name",
    "Manufacturer",
    "Model",
    "Serial Number",
    "Location",
    "Receive Date",
    "Register Date",
    "Purchase Year",
    "Asset Status",
)

# Part F.2: illustrative Asset Status mapping, pending confirmation against
# a real hospital inventory export (§14 open question 4). Keys are
# lowercased for case-insensitive exact-match lookup; an unrecognized
# value is a per-row failure, never a guess (Part F.1 step 3).
ASSET_STATUS_MAPPING: dict[str, EquipmentStatus] = {
    "active": EquipmentStatus.AVAILABLE_AT_POOL,
    "in use": EquipmentStatus.AVAILABLE_AT_POOL,
    "in service": EquipmentStatus.AVAILABLE_AT_POOL,
    "defective": EquipmentStatus.UNAVAILABLE_DEFECTIVE,
    "faulty": EquipmentStatus.UNAVAILABLE_DEFECTIVE,
    "under repair": EquipmentStatus.UNAVAILABLE_DEFECTIVE,
    "decommissioned": EquipmentStatus.DECOMMISSIONED,
    "disposed": EquipmentStatus.DECOMMISSIONED,
    "written off": EquipmentStatus.DECOMMISSIONED,
}


class ImportRowStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class ImportRowAction(str, Enum):
    CREATE = "create"
    UPDATE = "update"


@dataclass
class ImportRowResult:
    row_number: int
    bcm_code: str | None
    item_no: str | None
    asset_id: str | None
    status: ImportRowStatus
    action: ImportRowAction | None = None
    reason: str | None = None
    equipment_id: str | None = None


@dataclass
class ImportBatchResult:
    filename: str
    total_rows: int
    succeeded: int
    failed: int
    skipped: int
    rows: list[ImportRowResult]
    audit_log_id: str | None = None


@dataclass
class _RowPlan:
    result: ImportRowResult
    equipment_id: uuid.UUID | None = None
    create_data: dict | None = None
    update_data: dict | None = None
    import_source_metadata: dict | None = None


def _cell_to_text(value: object) -> str:
    """Best-effort text form of a raw openpyxl cell value, preserving BCM
    Code / Item No / Asset ID / Serial Number as strings throughout.

    Excel-side numeric coercion (a source column typed/formatted as a
    number in the spreadsheet itself, losing leading zeros before this
    file is even read) cannot be recovered here -- this only avoids
    *compounding* that loss (e.g. rendering an integer-valued float as
    "1.0" instead of "1").
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)
    if isinstance(value, int):
        return str(value)
    return str(value).strip()


def _load_worksheet(content: bytes) -> Worksheet:
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise InvalidInputError(
            "The uploaded file could not be read as a valid Excel (.xlsx) spreadsheet."
        ) from exc
    worksheet = workbook.active
    if worksheet is None:
        raise InvalidInputError("The uploaded spreadsheet has no worksheets.")
    return worksheet


def _validate_headers(worksheet: Worksheet) -> dict[str, int]:
    """Confirm every required header is present (Part F.1 step 2); reject
    the file outright with a clear message rather than a partial/guessed
    mapping. Returns {canonical_header: 0-based_column_index}."""
    header_row = next(worksheet.iter_rows(min_row=1, max_row=1, values_only=True), None)
    if header_row is None:
        raise InvalidInputError("The uploaded spreadsheet is empty; no header row was found.")

    found: dict[str, int] = {}
    for idx, raw in enumerate(header_row):
        text = _cell_to_text(raw)
        if not text:
            continue
        found[text.strip().lower()] = idx

    header_index: dict[str, int] = {}
    missing: list[str] = []
    for header in REQUIRED_HEADERS:
        idx = found.get(header.lower())
        if idx is None:
            missing.append(header)
        else:
            header_index[header] = idx
    if missing:
        raise InvalidInputError(
            "The uploaded spreadsheet is missing required column(s): " + ", ".join(missing)
        )
    return header_index


@dataclass
class _ParsedRow:
    row_number: int
    item_no_raw: str
    bcm_code_raw: str
    asset_id_raw: str
    equipment_name_raw: str
    brand_raw: str
    model_raw: str
    serial_number_raw: str
    location_raw: str
    receive_date_raw: str
    register_date_raw: str
    purchase_year_raw: str
    asset_status_raw: str


def _parse_rows(worksheet: Worksheet, header_index: dict[str, int]) -> list[_ParsedRow]:
    def cell(values: tuple, header: str) -> str:
        idx = header_index[header]
        return _cell_to_text(values[idx]) if idx < len(values) else ""

    parsed: list[_ParsedRow] = []
    for row_number, values in enumerate(worksheet.iter_rows(min_row=2, values_only=True), start=2):
        if values is None or all(v is None or _cell_to_text(v) == "" for v in values):
            continue  # trailing/blank row -- not counted, not reported
        parsed.append(
            _ParsedRow(
                row_number=row_number,
                item_no_raw=cell(values, "Item No."),
                bcm_code_raw=cell(values, "ID CODE"),
                asset_id_raw=cell(values, "Asset ID"),
                equipment_name_raw=cell(values, "Equipment Name"),
                brand_raw=cell(values, "Manufacturer"),
                model_raw=cell(values, "Model"),
                serial_number_raw=cell(values, "Serial Number"),
                location_raw=cell(values, "Location"),
                receive_date_raw=cell(values, "Receive Date"),
                register_date_raw=cell(values, "Register Date"),
                purchase_year_raw=cell(values, "Purchase Year"),
                asset_status_raw=cell(values, "Asset Status"),
            )
        )
    return parsed


def _find_in_file_duplicates(values: dict[int, str]) -> set[int]:
    """values: {row_number: normalized_value} for rows where the value is
    non-empty. Returns the set of row_numbers whose value appears more
    than once -- ALL occurrences fail, per Part F.1 step 3's recommended
    "flag all duplicates within a file" policy."""
    seen: dict[str, list[int]] = {}
    for row_number, value in values.items():
        seen.setdefault(value, []).append(row_number)
    duplicated_rows: set[int] = set()
    for rows in seen.values():
        if len(rows) > 1:
            duplicated_rows.update(rows)
    return duplicated_rows


async def _validate_rows(
    db: AsyncSession, parsed_rows: list[_ParsedRow], *, update_existing: bool
) -> list[_RowPlan]:
    plans: dict[int, _RowPlan] = {}
    normalized_bcm: dict[int, str] = {}
    normalized_item_no: dict[int, str] = {}
    normalized_asset_id: dict[int, str] = {}
    normalized_serial: dict[int, str] = {}

    # Pass 1: structural normalization. A row that fails here is final --
    # it never reaches a database check.
    for row in parsed_rows:
        if not row.bcm_code_raw:
            plans[row.row_number] = _RowPlan(
                result=ImportRowResult(
                    row_number=row.row_number,
                    bcm_code=None,
                    item_no=row.item_no_raw or None,
                    asset_id=row.asset_id_raw or None,
                    status=ImportRowStatus.FAILED,
                    reason="Missing BCM Code (ID CODE column).",
                )
            )
            continue
        try:
            bcm_code = normalize_bcm_code(row.bcm_code_raw)
        except InvalidInputError as exc:
            plans[row.row_number] = _RowPlan(
                result=ImportRowResult(
                    row_number=row.row_number,
                    bcm_code=None,
                    item_no=row.item_no_raw or None,
                    asset_id=row.asset_id_raw or None,
                    status=ImportRowStatus.FAILED,
                    reason=f"Invalid BCM Code: {exc.message}",
                )
            )
            continue

        item_no: str | None = None
        if row.item_no_raw:
            try:
                item_no = normalize_item_no(row.item_no_raw)
            except InvalidInputError as exc:
                plans[row.row_number] = _RowPlan(
                    result=ImportRowResult(
                        row_number=row.row_number,
                        bcm_code=bcm_code,
                        item_no=None,
                        asset_id=row.asset_id_raw or None,
                        status=ImportRowStatus.FAILED,
                        reason=f"Invalid Item No: {exc.message}",
                    )
                )
                continue

        normalized_bcm[row.row_number] = bcm_code
        if item_no:
            normalized_item_no[row.row_number] = item_no
        if row.asset_id_raw:
            normalized_asset_id[row.row_number] = row.asset_id_raw
        if row.serial_number_raw:
            normalized_serial[row.row_number] = row.serial_number_raw

    # Pass 2: in-file duplicate detection -- flags ALL occurrences.
    dup_bcm = _find_in_file_duplicates(normalized_bcm)
    dup_item_no = _find_in_file_duplicates(normalized_item_no)
    dup_asset_id = _find_in_file_duplicates(normalized_asset_id)
    dup_serial = _find_in_file_duplicates(normalized_serial)

    for row in parsed_rows:
        if row.row_number in plans:
            continue
        bcm_code = normalized_bcm[row.row_number]
        item_no = normalized_item_no.get(row.row_number)
        asset_id = normalized_asset_id.get(row.row_number) or None
        serial_number = normalized_serial.get(row.row_number) or None

        if row.row_number in dup_bcm:
            plans[row.row_number] = _RowPlan(
                result=ImportRowResult(
                    row_number=row.row_number,
                    bcm_code=bcm_code,
                    item_no=item_no,
                    asset_id=asset_id,
                    status=ImportRowStatus.FAILED,
                    reason="Duplicate BCM Code within the uploaded file.",
                )
            )
            continue
        if row.row_number in dup_item_no:
            plans[row.row_number] = _RowPlan(
                result=ImportRowResult(
                    row_number=row.row_number,
                    bcm_code=bcm_code,
                    item_no=item_no,
                    asset_id=asset_id,
                    status=ImportRowStatus.FAILED,
                    reason="Duplicate Item No within the uploaded file.",
                )
            )
            continue
        if row.row_number in dup_asset_id:
            plans[row.row_number] = _RowPlan(
                result=ImportRowResult(
                    row_number=row.row_number,
                    bcm_code=bcm_code,
                    item_no=item_no,
                    asset_id=asset_id,
                    status=ImportRowStatus.FAILED,
                    reason="Duplicate Asset ID within the uploaded file.",
                )
            )
            continue
        if row.row_number in dup_serial:
            plans[row.row_number] = _RowPlan(
                result=ImportRowResult(
                    row_number=row.row_number,
                    bcm_code=bcm_code,
                    item_no=item_no,
                    asset_id=asset_id,
                    status=ImportRowStatus.FAILED,
                    reason="Duplicate Serial Number within the uploaded file.",
                )
            )
            continue

    # Pass 3: database checks, only for rows still unresolved.
    for row in parsed_rows:
        if row.row_number in plans:
            continue
        bcm_code = normalized_bcm[row.row_number]
        item_no = normalized_item_no.get(row.row_number)
        asset_id = normalized_asset_id.get(row.row_number) or None
        serial_number = normalized_serial.get(row.row_number) or None

        existing = await equipment_crud.get_by_bcm_code(db, bcm_code)
        if existing is not None and not update_existing:
            plans[row.row_number] = _RowPlan(
                result=ImportRowResult(
                    row_number=row.row_number,
                    bcm_code=bcm_code,
                    item_no=item_no,
                    asset_id=asset_id,
                    status=ImportRowStatus.SKIPPED,
                    reason="BCM Code already exists in the database (update mode is off).",
                )
            )
            continue

        # Asset Status: validated for every remaining row, whether create
        # or update (Part F.1 step 3's per-row rule is unconditional) --
        # even though an update row never writes `status`, raw_source_
        # status is only ever persisted for rows whose source value could
        # be classified at all.
        mapped_status = ASSET_STATUS_MAPPING.get(row.asset_status_raw.strip().lower())
        if mapped_status is None:
            plans[row.row_number] = _RowPlan(
                result=ImportRowResult(
                    row_number=row.row_number,
                    bcm_code=bcm_code,
                    item_no=item_no,
                    asset_id=asset_id,
                    status=ImportRowStatus.FAILED,
                    reason=f"Unrecognized Asset Status value: '{row.asset_status_raw}'.",
                )
            )
            continue

        import_source_metadata = {
            "location": row.location_raw or None,
            "receive_date": row.receive_date_raw or None,
            "register_date": row.register_date_raw or None,
            "purchase_year": row.purchase_year_raw or None,
        }

        if existing is None:
            # CREATE path.
            if not row.equipment_name_raw:
                plans[row.row_number] = _RowPlan(
                    result=ImportRowResult(
                        row_number=row.row_number,
                        bcm_code=bcm_code,
                        item_no=item_no,
                        asset_id=asset_id,
                        status=ImportRowStatus.FAILED,
                        reason="Equipment Name is required.",
                    )
                )
                continue

            conflict_reason = await _find_create_conflict(
                db, bcm_code=bcm_code, item_no=item_no, serial_number=serial_number, asset_id=asset_id
            )
            if conflict_reason is not None:
                plans[row.row_number] = _RowPlan(
                    result=ImportRowResult(
                        row_number=row.row_number,
                        bcm_code=bcm_code,
                        item_no=item_no,
                        asset_id=asset_id,
                        status=ImportRowStatus.FAILED,
                        reason=conflict_reason,
                    )
                )
                continue

            create_data = {
                "asset_number": bcm_code,
                "bcm_code": bcm_code,
                "item_no": item_no,
                "asset_id": asset_id,
                "serial_number": serial_number,
                "equipment_name": row.equipment_name_raw,
                "brand": row.brand_raw or None,
                "model": row.model_raw or None,
                "raw_source_status": row.asset_status_raw or None,
                "status": mapped_status,
                "equipment_metadata": {"import_source": import_source_metadata},
            }
            plans[row.row_number] = _RowPlan(
                result=ImportRowResult(
                    row_number=row.row_number,
                    bcm_code=bcm_code,
                    item_no=item_no,
                    asset_id=asset_id,
                    status=ImportRowStatus.SUCCESS,
                    action=ImportRowAction.CREATE,
                ),
                create_data=create_data,
            )
        else:
            # UPDATE path (Part F.3): only the approved master-data field
            # set -- never status/legacy_status/asset_number/item_no/
            # serial_number/equipment_name/bcm_code.
            if asset_id is not None:
                other = await equipment_crud.get_by_asset_id(db, asset_id)
                if other is not None and other.id != existing.id:
                    plans[row.row_number] = _RowPlan(
                        result=ImportRowResult(
                            row_number=row.row_number,
                            bcm_code=bcm_code,
                            item_no=item_no,
                            asset_id=asset_id,
                            status=ImportRowStatus.FAILED,
                            reason="Asset ID already belongs to a different equipment record.",
                        )
                    )
                    continue

            update_data = {
                "asset_id": asset_id,
                "brand": row.brand_raw or None,
                "model": row.model_raw or None,
                "raw_source_status": row.asset_status_raw or None,
            }
            plans[row.row_number] = _RowPlan(
                result=ImportRowResult(
                    row_number=row.row_number,
                    bcm_code=bcm_code,
                    item_no=item_no,
                    asset_id=asset_id,
                    status=ImportRowStatus.SUCCESS,
                    action=ImportRowAction.UPDATE,
                ),
                equipment_id=existing.id,
                update_data=update_data,
                import_source_metadata=import_source_metadata,
            )

    # Preserve original row order.
    return [plans[row.row_number] for row in parsed_rows]


async def _find_create_conflict(
    db: AsyncSession, *, bcm_code: str, item_no: str | None, serial_number: str | None, asset_id: str | None
) -> str | None:
    """Roadmap PR12: proactive database duplicate checks for a row about
    to become a new equipment record, so an expected conflict is reported
    as a per-row validation failure rather than surfacing as an
    IntegrityError during the commit write phase."""
    if await equipment_crud.get_by_asset_number(db, bcm_code) is not None:
        return "Generated asset_number (from BCM Code) conflicts with an existing equipment record."
    if item_no is not None and await equipment_crud.get_by_item_no(db, item_no) is not None:
        return "Item No already belongs to a different equipment record."
    if serial_number is not None and await equipment_crud.get_by_serial_number(db, serial_number) is not None:
        return "Serial Number already belongs to a different equipment record."
    if asset_id is not None and await equipment_crud.get_by_asset_id(db, asset_id) is not None:
        return "Asset ID already belongs to a different equipment record."
    return None


def _summarize(filename: str, plans: list[_RowPlan]) -> ImportBatchResult:
    rows = [plan.result for plan in plans]
    return ImportBatchResult(
        filename=filename,
        total_rows=len(rows),
        succeeded=sum(1 for r in rows if r.status == ImportRowStatus.SUCCESS),
        failed=sum(1 for r in rows if r.status == ImportRowStatus.FAILED),
        skipped=sum(1 for r in rows if r.status == ImportRowStatus.SKIPPED),
        rows=rows,
    )


class ImportCommitFailedError(DomainError):
    """Unexpected failure during the commit write phase (Roadmap PR12) --
    the entire batch is rolled back, never partially committed. Distinct
    from any per-row validation failure, which never reaches the write
    phase at all and does not raise."""

    code = "IMPORT_COMMIT_FAILED"
    status_code = 500


async def _commit_rows(
    db: AsyncSession,
    *,
    filename: str,
    plans: list[_RowPlan],
    update_existing: bool,
    actor_user_id: uuid.UUID | None,
    request: Request | None,
) -> ImportBatchResult:
    try:
        for plan in plans:
            if plan.result.status != ImportRowStatus.SUCCESS:
                continue
            if plan.result.action == ImportRowAction.CREATE:
                equipment = await equipment_crud.create(db, data=plan.create_data)
                plan.result.equipment_id = str(equipment.id)
            else:
                existing = await equipment_crud.get_by_id(db, plan.equipment_id)
                if existing is None:
                    raise ImportCommitFailedError(
                        f"Equipment {plan.equipment_id} no longer exists mid-commit."
                    )
                merged_metadata = dict(existing.equipment_metadata or {})
                merged_metadata["import_source"] = plan.import_source_metadata
                update_payload = dict(plan.update_data)
                update_payload["equipment_metadata"] = merged_metadata
                await equipment_crud.update(db, existing, data=update_payload)
                plan.result.equipment_id = str(existing.id)

        summary = _summarize(filename, plans)
        audit_log = await record_audit_event(
            db,
            actor_user_id=actor_user_id,
            action=AUDIT_ACTION_IMPORT,
            entity_type=AUDIT_ENTITY_EQUIPMENT,
            entity_id=None,
            after={
                "filename": filename,
                "total_rows": summary.total_rows,
                "succeeded": summary.succeeded,
                "failed": summary.failed,
                "skipped": summary.skipped,
                "update_existing": update_existing,
            },
            request=request,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.exception("Inventory import commit failed unexpectedly; batch rolled back (filename=%s)", filename)
        if isinstance(exc, ImportCommitFailedError):
            raise
        raise ImportCommitFailedError(
            "Import commit failed unexpectedly due to a system error. No rows were saved; please retry."
        ) from exc

    summary.audit_log_id = str(audit_log.id)
    return summary


async def process_import(
    db: AsyncSession,
    *,
    file: UploadFile,
    update_existing: bool,
    commit: bool,
    actor_user_id: uuid.UUID | None = None,
    request: Request | None = None,
) -> ImportBatchResult:
    """Single entry point for both preview (`commit=False`) and commit
    (`commit=True`). Always re-parses and re-validates the uploaded file
    from scratch -- commit never trusts a prior preview result, so a
    stale or tampered client-supplied preview payload cannot influence
    what actually gets written.
    """
    content = await file.read()
    worksheet = _load_worksheet(content)
    header_index = _validate_headers(worksheet)
    parsed_rows = _parse_rows(worksheet, header_index)
    plans = await _validate_rows(db, parsed_rows, update_existing=update_existing)

    if not commit:
        return _summarize(file.filename or "upload.xlsx", plans)

    return await _commit_rows(
        db,
        filename=file.filename or "upload.xlsx",
        plans=plans,
        update_existing=update_existing,
        actor_user_id=actor_user_id,
        request=request,
    )
