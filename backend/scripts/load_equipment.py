#!/usr/bin/env python3
"""Re-runnable loader for the hospital's pool equipment export (Excel).

Modelled on scripts/load_master_data.py. The input file is supplied at run
time and is never committed -- no hospital data lives in the repository.

Accepted files: .xlsx, .xlsm and .xltx/.xltm (Excel templates; openpyxl cannot
open these directly, so a temporary copy with the content type patched is
read -- the original is never modified). Only the FIRST sheet is read. The
header row is located by name within the first rows (no hard-coded row
numbers); the summary line above it is ignored.

Columns used (by header text, trimmed):
    Item No.        -> item_no   (text, leading zeros kept)
    ID CODE         -> bcm_code  (app.services.identifiers.normalize_bcm_code)
    Asset ID        -> asset_id  (asset_number is never written; stays NULL)
    ชื่อเครื่องมือ     -> category (exact, case-insensitive, trimmed match to an
                       EXISTING category; no match = row error) and
                       equipment_name (= the category's stored name)
    ยี่ห้อ / รุ่น / S/N -> brand / model / serial_number ('-' or blank = none)
    Asset status    -> status (also kept verbatim in raw_source_status):
                       Active -> available_at_pool
                       Defective -> unavailable_defective
                       Decommission, Wait decom -> decommissioned
    ยังไม่ส่งคืน       -> optional. Owner decision "ข": it does NOT affect status
                       (every Active row loads as available_at_pool); rows
                       marked are only COUNTED and reported with a warning.
Dates, location and price columns are ignored (out of scope).

Rules:
  * Existing equipment is matched by canonical BCM code. Status of an
    existing row is NEVER changed. Without --update-existing a row whose
    brand/model/serial/asset_id/item_no differ is reported SKIP; with it, the
    differing fields are updated. A blank value in the file never clears a
    stored value.
  * New equipment is created through app.crud.equipment.create (the same path
    as POST /equipment, which writes no initial status-history row).
  * Errors (missing headers, unknown status or category, blank/invalid BCM,
    duplicate BCM / Item No / serial in the file, Item No or serial already
    used by a different equipment in the database) abort the run: nothing is
    written, in dry-run or --apply.

Dry-run is the default. --apply writes everything in ONE transaction with ONE
audit entry (action "import", actor NULL = system, like load_master_data).

Exit codes: 0 ok; 1 apply failed; 2 input/validation errors (nothing written).
"""

import argparse
import asyncio
import re
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.audit import (  # noqa: E402
    AUDIT_ACTION_IMPORT,
    AUDIT_ENTITY_EQUIPMENT,
    record_audit_event,
)
from app.core.exceptions import InvalidInputError  # noqa: E402
from app.crud import equipment as equipment_crud  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.equipment import EquipmentStatus  # noqa: E402
from app.models.master_data import EquipmentCategory  # noqa: E402
from app.services.identifiers import normalize_bcm_code, normalize_item_no  # noqa: E402

H_ITEM, H_BCM, H_ASSET = "Item No.", "ID CODE", "Asset ID"
H_NAME, H_BRAND, H_MODEL, H_SERIAL = "ชื่อเครื่องมือ", "ยี่ห้อ", "รุ่น", "S/N"
H_STATUS, H_NOT_RETURNED = "Asset status", "ยังไม่ส่งคืน"
REQUIRED_HEADERS = [H_ITEM, H_BCM, H_ASSET, H_NAME, H_BRAND, H_MODEL, H_SERIAL, H_STATUS]
HEADER_SCAN_ROWS = 30
MAX_LEN = {"brand": 100, "model": 100, "serial_number": 100, "asset_id": 100, "equipment_name": 255}
EXCEL_SUFFIXES = {".xlsx", ".xlsm", ".xltx", ".xltm"}
TEMPLATE_SUFFIXES = {".xltx", ".xltm"}
STATUS_MAP = {
    "active": EquipmentStatus.AVAILABLE_AT_POOL,
    "defective": EquipmentStatus.UNAVAILABLE_DEFECTIVE,
    "decommission": EquipmentStatus.DECOMMISSIONED,
    "wait decom": EquipmentStatus.DECOMMISSIONED,
}
NOT_MARKED = {"", "0", "-", "false", "no", "n", "none", "null"}


class InputError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class PoolRow:
    line: int
    item_no: str | None
    bcm_code: str | None
    asset_id: str | None
    name: str
    brand: str | None
    model: str | None
    serial_number: str | None
    raw_status: str
    status: EquipmentStatus | None
    not_returned: bool


@dataclass
class PlanItem:
    line: int
    bcm_code: str
    action: str  # create | unchanged | update | skip
    status: EquipmentStatus | None = None
    detail: str = ""
    data: dict = field(default_factory=dict, repr=False)  # create payload / update changes
    entity: object = field(default=None, repr=False)
    before: dict = field(default_factory=dict, repr=False)


def _patched_copy(path: Path, workdir: Path) -> Path:
    """Copy of an Excel template with its content type changed to a normal
    workbook so openpyxl accepts it."""
    dest = workdir / (path.stem + ".xlsx")
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "[Content_Types].xml":
                data = data.replace(b"template.macroEnabled.main+xml", b"sheet.macroEnabled.main+xml")
                data = data.replace(b"template.main+xml", b"sheet.main+xml")
            zout.writestr(info, data)
    return dest


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _err_text(exc: Exception) -> str:
    return str(getattr(exc, "detail", None) or exc)


def read_pool_sheet(path: Path) -> tuple[list[tuple[int, dict[str, str]]], bool]:
    """Returns ([(excel_row_number, {header: text})], has_not_returned_column)."""
    from openpyxl import load_workbook

    if path.suffix.lower() not in EXCEL_SUFFIXES:
        raise InputError([f"{path.name}: unsupported file type (expected .xlsx, .xlsm, .xltx or .xltm)"])
    if not path.is_file():
        raise InputError([f"cannot read {path}: file not found"])
    with tempfile.TemporaryDirectory() as tmp:
        src = path
        if path.suffix.lower() in TEMPLATE_SUFFIXES:
            try:
                src = _patched_copy(path, Path(tmp))
            except (zipfile.BadZipFile, OSError) as exc:
                raise InputError([f"{path.name}: not a readable Excel file ({exc})"]) from exc
        try:
            wb = load_workbook(src, read_only=True, data_only=True)
        except Exception as exc:  # openpyxl raises many types for corrupt files
            raise InputError([f"{path.name}: cannot open as Excel ({type(exc).__name__}: {exc})"]) from exc
        try:
            rows = [tuple(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
        finally:
            wb.close()

    header_idx, cols = None, {}
    for i, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        found: dict[str, int] = {}
        for j, v in enumerate(row):
            t = _cell_text(v)
            if t and t not in found:
                found[t] = j
        if all(h in found for h in REQUIRED_HEADERS):
            header_idx, cols = i, found
            break
    if header_idx is None:
        best = max((set(_cell_text(v) for v in r) for r in rows[:HEADER_SCAN_ROWS]),
                   key=lambda s: len(s & set(REQUIRED_HEADERS)), default=set())
        missing = [h for h in REQUIRED_HEADERS if h not in best]
        raise InputError([f"{path.name}: header row not found in the first {HEADER_SCAN_ROWS} rows of the first sheet; "
                          f"missing headers: {', '.join(missing)}"])
    has_nr = H_NOT_RETURNED in cols
    wanted = REQUIRED_HEADERS + ([H_NOT_RETURNED] if has_nr else [])
    out = []
    for i in range(header_idx + 1, len(rows)):
        row = rows[i]
        rec = {h: _cell_text(row[cols[h]]) if cols[h] < len(row) else "" for h in wanted}
        if all(v == "" for v in rec.values()):
            continue
        out.append((i + 1, rec))
    return out, has_nr


def parse_rows(path: Path) -> tuple[list[PoolRow], list[str], bool]:
    """Returns (rows, row_errors, has_not_returned_column)."""
    raw_rows, has_nr = read_pool_sheet(path)
    rows, errors = [], []
    seen_bcm: dict[str, int] = {}
    seen_item: dict[str, int] = {}
    seen_serial: dict[str, int] = {}
    for line, r in raw_rows:
        pre = f"{path.name} row {line}"
        bcm = None
        if not r[H_BCM]:
            errors.append(f"{pre}: ID CODE (BCM) is blank")
        else:
            try:
                bcm = normalize_bcm_code(r[H_BCM])
            except InvalidInputError as exc:
                errors.append(f"{pre}: ID CODE {r[H_BCM]!r}: {_err_text(exc)}")
        item = None
        if r[H_ITEM]:
            try:
                item = normalize_item_no(r[H_ITEM])
            except InvalidInputError as exc:
                errors.append(f"{pre}: Item No. {r[H_ITEM]!r}: {_err_text(exc)}")
        raw_status = r[H_STATUS]
        status = STATUS_MAP.get(re.sub(r"\s+", " ", raw_status).casefold())
        if status is None:
            errors.append(f"{pre}: unknown Asset status {raw_status!r} (expected Active, Defective, Decommission or Wait decom)")
        if not r[H_NAME]:
            errors.append(f"{pre}: ชื่อเครื่องมือ is blank")
        serial = r[H_SERIAL] if r[H_SERIAL] not in ("", "-") else None
        vals = {"brand": r[H_BRAND] or None, "model": r[H_MODEL] or None,
                "serial_number": serial, "asset_id": r[H_ASSET] or None}
        for k, v in vals.items():
            if v is not None and len(v) > MAX_LEN[k]:
                errors.append(f"{pre}: {k} longer than {MAX_LEN[k]} characters")
        if bcm:
            if bcm in seen_bcm:
                errors.append(f"{pre}: duplicate BCM {bcm} (first on row {seen_bcm[bcm]})")
            seen_bcm.setdefault(bcm, line)
        if item:
            if item in seen_item:
                errors.append(f"{pre}: duplicate Item No {item!r} (first on row {seen_item[item]})")
            seen_item.setdefault(item, line)
        if serial:
            if serial in seen_serial:
                errors.append(f"{pre}: duplicate S/N {serial!r} (first on row {seen_serial[serial]})")
            seen_serial.setdefault(serial, line)
        nr = has_nr and r.get(H_NOT_RETURNED, "").strip().casefold() not in NOT_MARKED
        rows.append(PoolRow(line, item, bcm, vals["asset_id"], r[H_NAME], vals["brand"], vals["model"],
                            serial, raw_status, status, nr))
    if not rows and not errors:
        errors.append(f"{path.name}: no data rows")
    return rows, errors, has_nr


async def build_plan(db, rows: list[PoolRow], *, update_existing: bool, file_errors: list[str], file_name: str):
    """Returns (plan, errors)."""
    errors = list(file_errors)
    cats: dict[str, list[EquipmentCategory]] = {}
    for c in (await db.execute(select(EquipmentCategory))).scalars().all():
        cats.setdefault(c.name.strip().casefold(), []).append(c)
    by_bcm = await equipment_crud.get_by_bcm_codes(db, [r.bcm_code for r in rows if r.bcm_code])
    by_item = await equipment_crud.get_by_item_nos(db, [r.item_no for r in rows if r.item_no])
    by_serial = await equipment_crud.get_by_serial_numbers(db, [r.serial_number for r in rows if r.serial_number])

    plan: list[PlanItem] = []
    for r in rows:
        if not r.bcm_code:
            continue  # already reported as an error
        pre = f"{file_name} row {r.line}"
        matches = cats.get(r.name.strip().casefold(), [])
        category = matches[0] if len(matches) == 1 else None
        if not matches and r.name:
            errors.append(f"{pre}: no existing category named {r.name!r} (load categories first, runbook 8.5)")
        elif len(matches) > 1:
            errors.append(f"{pre}: more than one category matches {r.name!r}")
        existing = by_bcm.get(r.bcm_code)
        other = by_item.get(r.item_no) if r.item_no else None
        if other is not None and other is not existing:
            errors.append(f"{pre}: Item No {r.item_no!r} is already used by {other.bcm_code or 'equipment without a BCM'}")
        other = by_serial.get(r.serial_number) if r.serial_number else None
        if other is not None and other is not existing:
            errors.append(f"{pre}: S/N {r.serial_number!r} is already used by {other.bcm_code or 'equipment without a BCM'}")
        if existing is None:
            data = {
                "bcm_code": r.bcm_code, "item_no": r.item_no, "asset_number": None, "asset_id": r.asset_id,
                "equipment_name": category.name if category else r.name,
                "category_id": category.id if category else None,
                "brand": r.brand, "model": r.model, "serial_number": r.serial_number,
                "status": r.status, "raw_source_status": r.raw_status or None,
            }
            plan.append(PlanItem(r.line, r.bcm_code, "create", status=r.status, data=data))
            continue
        want = {"brand": r.brand, "model": r.model, "serial_number": r.serial_number,
                "asset_id": r.asset_id, "item_no": r.item_no}
        changes = {k: v for k, v in want.items() if v is not None and getattr(existing, k) != v}
        if not changes:
            plan.append(PlanItem(r.line, r.bcm_code, "unchanged", status=existing.status, entity=existing))
        elif update_existing:
            before = {k: getattr(existing, k) for k in changes}
            plan.append(PlanItem(r.line, r.bcm_code, "update", status=existing.status,
                                 detail="changes: " + ", ".join(changes), data=changes, entity=existing, before=before))
        else:
            plan.append(PlanItem(r.line, r.bcm_code, "skip", status=existing.status, entity=existing,
                                 detail="differs in " + ", ".join(changes) + " (use -UpdateExisting)"))
    return plan, errors


def summarize(plan: list[PlanItem], rows: list[PoolRow], has_nr_col: bool) -> dict:
    counts: dict[str, int] = {}
    statuses: dict[str, int] = {}
    for p in plan:
        counts[p.action] = counts.get(p.action, 0) + 1
        if p.action == "create" and p.status is not None:
            statuses[p.status.value] = statuses.get(p.status.value, 0) + 1
    return {
        "rows": len(rows),
        "create": counts.get("create", 0), "update": counts.get("update", 0),
        "unchanged": counts.get("unchanged", 0), "skip": counts.get("skip", 0),
        "status_of_new": statuses,
        "not_returned": sum(1 for r in rows if r.not_returned),
        "has_not_returned_column": has_nr_col,
    }


def format_plan(plan: list[PlanItem], summary: dict, errors: list[str]) -> str:
    lines = [f"--- equipment ({len(plan)}) ---"]
    for p in plan:
        bits = [f"{p.action.upper():9}", p.bcm_code]
        if p.status:
            bits.append(p.status.value)
        if p.detail:
            bits.append(f"[{p.detail}]")
        lines.append("  " + " ".join(bits))
    lines.append(f"Summary: rows={summary['rows']}, create={summary['create']}, update={summary['update']}, "
                 f"unchanged={summary['unchanged']}, skip={summary['skip']}, error={len(errors)}")
    by_status = ", ".join(f"{k}={v}" for k, v in sorted(summary["status_of_new"].items())) or "none"
    lines.append(f"New equipment by status: {by_status}")
    if summary["has_not_returned_column"]:
        lines.append(f"Rows marked 'ยังไม่ส่งคืน' (not returned): {summary['not_returned']}")
        if summary["not_returned"]:
            lines.append("WARNING: per Owner decision, rows marked not-returned load by their Asset status (Active = "
                         "available_at_pool). Staff must not dispatch an item that is not physically on the shelf.")
    else:
        lines.append("Column 'ยังไม่ส่งคืน' not present: not-returned count = 0")
    return "\n".join(lines)


async def apply_plan(db, plan: list[PlanItem], summary: dict, *, update_existing: bool) -> dict:
    """Writes inside the caller's transaction (no commit here)."""
    created, updated = [], []
    for p in plan:
        if p.action == "create":
            eq = await equipment_crud.create(db, data=dict(p.data))
            created.append({"id": str(eq.id), "bcm_code": p.bcm_code, "status": p.status.value})
        elif p.action == "update":
            await equipment_crud.update(db, p.entity, data=dict(p.data))
            updated.append({"id": str(p.entity.id), "bcm_code": p.bcm_code, "before": p.before, "after": p.data})
    after = {"kind": "pool_equipment_load", "update_existing": update_existing, "created": created,
             "updated": updated, "not_returned_rows": summary["not_returned"]}
    if created or updated:  # no audit noise on a no-op re-run
        await record_audit_event(db, actor_user_id=None, action=AUDIT_ACTION_IMPORT,
                                 entity_type=AUDIT_ENTITY_EQUIPMENT, entity_id=None, after=after)
    return after


async def run(pool_path: Path, *, apply: bool, update_existing: bool, out=print) -> int:
    try:
        rows, file_errors, has_nr = parse_rows(pool_path)
    except InputError as exc:
        out("INPUT ERRORS (nothing was written):")
        for e in exc.errors:
            out(f"  - {e}")
        return 2
    async with AsyncSessionLocal() as db:
        plan, errors = await build_plan(db, rows, update_existing=update_existing,
                                        file_errors=file_errors, file_name=pool_path.name)
        summary = summarize(plan, rows, has_nr)
        out(format_plan(plan, summary, errors))
        if errors:
            out("INPUT ERRORS (nothing was written):")
            for e in errors:
                out(f"  - {e}")
            return 2
        if not apply:
            out("DRY RUN: nothing was written. Re-run with --apply to write this plan.")
            return 0
        try:
            await apply_plan(db, plan, summary, update_existing=update_existing)
            await db.commit()
        except Exception as exc:  # whole load is one transaction
            await db.rollback()
            out(f"APPLY FAILED, nothing was written: {type(exc).__name__}: {exc}")
            return 1
    out("APPLIED: all rows written in one transaction with one audit entry.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pool-file", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="write the plan (default is a dry run)")
    parser.add_argument("--update-existing", action="store_true",
                        help="update brand/model/serial/asset_id/item_no of existing equipment (never status)")
    args = parser.parse_args(argv)
    return asyncio.run(run(args.pool_file, apply=args.apply, update_existing=args.update_existing))


if __name__ == "__main__":
    raise SystemExit(main())
