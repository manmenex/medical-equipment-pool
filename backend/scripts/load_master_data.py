#!/usr/bin/env python3
"""One-time, re-runnable loader for production master data (Owner decision
2026-10-13): departments, wards and equipment categories whose names must
match the external Nsmart Realtime tool exactly.

Inputs are two CSV files supplied at run time (never committed -- no
hospital data lives in the repository):

    --wards FILE        header: ward_name,nsmart_department,phone
    --categories FILE   header: category_name

Rules:
  * Names are used exactly as written (surrounding whitespace trimmed only).
  * Departments = the distinct non-blank nsmart_department values. A
    department's phone is the phone of its rows; if rows sharing a department
    disagree on the phone, the conflict is reported and the phone skipped.
  * Wards link to their department (none when nsmart_department is blank).
  * Existing rows are matched by exact NAME and left as-is ("exists"); a phone
    is only filled when the row has none, unless --overwrite-phones. Nothing
    is ever deleted or renamed, and an existing row's code never changes.

CODE RULE (Ward.code / Department.code are required, unique, <= 20 chars):
  new departments get D001, D002, ...; new wards get W001, W002, ...
  A new code is "<prefix><n>" where n is one more than the highest number
  already used by an existing code of that prefix (codes of any other shape
  are ignored), assigned in CSV order (departments in order of first
  appearance). The same CSV loaded into an empty database always yields the
  same codes; on a re-run, rows that already exist are matched by name and
  keep their code, so nothing is renumbered.

Dry-run is the default: it prints a per-row plan and writes nothing.
--apply writes everything in ONE transaction with ONE batch audit entry
(action "import", PR12 convention). The audit actor is NULL (system), the
same convention as app.scripts.bootstrap_admin: no authenticated user exists
for a command-line operation. The audit entry lists what was created, never
the CSV files themselves.

Exit codes: 0 ok; 1 apply failed; 2 input/validation errors (nothing written).
"""

import argparse
import asyncio
import csv
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.audit import (  # noqa: E402
    AUDIT_ACTION_IMPORT,
    AUDIT_ENTITY_WARD,
    record_audit_event,
)
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.master_data import Department, EquipmentCategory, Ward  # noqa: E402
from app.schemas.master_data import _validate_contact_phone  # noqa: E402

WARD_HEADER = ["ward_name", "nsmart_department", "phone"]
CATEGORY_HEADER = ["category_name"]
CODE_MAX_LENGTH = 20
NAME_MAX = {"ward": 150, "department": 150, "category": 100}


class InputError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class WardRow:
    line: int
    name: str
    department: str | None
    phone: str | None


@dataclass
class PlanItem:
    kind: str  # department | ward | category
    name: str
    action: str  # create | exists | skip
    code: str | None = None
    phone: str | None = None
    detail: str = ""
    # internal
    entity: object = field(default=None, repr=False)
    set_phone: str | None = None  # phone to write onto an existing row


def _read_rows(path: Path, header: list[str]) -> list[tuple[int, dict[str, str]]]:
    try:
        # utf-8-sig strips an Excel/Notepad BOM; newline="" per csv docs.
        with open(path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            got = [(h or "").strip() for h in (reader.fieldnames or [])]
            if got != header:
                raise InputError([f"{path.name}: header must be exactly {','.join(header)} (got {','.join(got) or 'nothing'})"])
            reader.fieldnames = got
            out = []
            for row in reader:
                if None in row:
                    raise InputError([f"{path.name} line {reader.line_num}: too many columns"])
                if all((v or "").strip() == "" for v in row.values()):
                    continue  # fully blank line
                out.append((reader.line_num, {k: (v or "").strip() for k, v in row.items()}))
            return out
    except UnicodeDecodeError as exc:
        raise InputError([f"{path.name}: not valid UTF-8 ({exc.reason})"]) from exc
    except OSError as exc:
        raise InputError([f"cannot read {path}: {exc.strerror}"]) from exc


def parse_wards(path: Path) -> list[WardRow]:
    rows, errors, seen = [], [], {}
    for line, r in _read_rows(path, WARD_HEADER):
        name = r["ward_name"]
        if not name:
            errors.append(f"{path.name} line {line}: ward_name is blank")
            continue
        if len(name) > NAME_MAX["ward"]:
            errors.append(f"{path.name} line {line}: ward_name longer than {NAME_MAX['ward']} characters")
        if name in seen:
            errors.append(f"{path.name} line {line}: duplicate ward_name {name!r} (first on line {seen[name]})")
        seen.setdefault(name, line)
        dept = r["nsmart_department"] or None
        if dept and len(dept) > NAME_MAX["department"]:
            errors.append(f"{path.name} line {line}: nsmart_department longer than {NAME_MAX['department']} characters")
        try:
            phone = _validate_contact_phone(r["phone"])
        except ValueError as exc:
            errors.append(f"{path.name} line {line}: {name!r}: {exc}")
            phone = None
        rows.append(WardRow(line, name, dept, phone))
    if errors:
        raise InputError(errors)
    if not rows:
        raise InputError([f"{path.name}: no data rows"])
    return rows


def parse_categories(path: Path) -> list[str]:
    names, errors, seen = [], [], {}
    for line, r in _read_rows(path, CATEGORY_HEADER):
        name = r["category_name"]
        if not name:
            errors.append(f"{path.name} line {line}: category_name is blank")
            continue
        if len(name) > NAME_MAX["category"]:
            errors.append(f"{path.name} line {line}: category_name longer than {NAME_MAX['category']} characters")
        if name in seen:
            errors.append(f"{path.name} line {line}: duplicate category_name {name!r} (first on line {seen[name]})")
        seen.setdefault(name, line)
        names.append(name)
    if errors:
        raise InputError(errors)
    if not names:
        raise InputError([f"{path.name}: no data rows"])
    return names


def _next_number(existing_codes, prefix: str) -> int:
    highest = 0
    for code in existing_codes:
        tail = code[len(prefix):]
        if code.startswith(prefix) and tail.isascii() and tail.isdigit():
            highest = max(highest, int(tail))
    return highest + 1


def make_code(prefix: str, n: int) -> str:
    code = f"{prefix}{n:03d}"
    assert len(code) <= CODE_MAX_LENGTH
    return code


def _phone_decision(existing: str | None, wanted: str | None, overwrite: bool) -> tuple[str | None, str]:
    """Returns (phone_to_write_or_None, note) for an EXISTING row."""
    if not wanted:
        return None, ""
    if existing == wanted:
        return None, "phone unchanged"
    if not existing:
        return wanted, "phone will be set"
    if overwrite:
        return wanted, f"phone will be overwritten (was {existing})"
    return None, f"has phone {existing}; kept (use --overwrite-phones)"


async def build_plan(db, wards: list[WardRow], categories: list[str], *, overwrite_phones: bool = False) -> list[PlanItem]:
    plan: list[PlanItem] = []

    # ---- departments
    dept_order: list[str] = []
    dept_phones: dict[str, set[str]] = {}
    for w in wards:
        if w.department:
            if w.department not in dept_phones:
                dept_order.append(w.department)
                dept_phones[w.department] = set()
            if w.phone:
                dept_phones[w.department].add(w.phone)

    db_depts: dict[str, list[Department]] = {}
    all_dept_codes = []
    for d in (await db.execute(select(Department))).scalars().all():
        db_depts.setdefault(d.name.strip(), []).append(d)
        all_dept_codes.append(d.code)
    next_d = _next_number(all_dept_codes, "D")
    dept_by_name: dict[str, PlanItem] = {}
    for name in dept_order:
        phones = dept_phones[name]
        phone_note = ""
        phone = None
        if len(phones) > 1:
            phone_note = "phone conflict between ward rows (" + " / ".join(sorted(phones)) + "); phone skipped"
        elif phones:
            phone = next(iter(phones))
        matches = db_depts.get(name, [])
        if len(matches) > 1:
            item = PlanItem("department", name, "skip", detail="more than one department already has this exact name")
        elif matches:
            set_phone, note = _phone_decision(matches[0].phone, phone, overwrite_phones)
            item = PlanItem("department", name, "exists", code=matches[0].code, phone=phone,
                            detail="; ".join(x for x in (note, phone_note) if x), entity=matches[0], set_phone=set_phone)
        else:
            item = PlanItem("department", name, "create", code=make_code("D", next_d), phone=phone, detail=phone_note)
            next_d += 1
        dept_by_name[name] = item
        plan.append(item)

    # ---- wards
    db_wards: dict[str, list[Ward]] = {}
    all_ward_codes = []
    for w in (await db.execute(select(Ward))).scalars().all():
        db_wards.setdefault(w.name.strip(), []).append(w)
        all_ward_codes.append(w.code)
    next_w = _next_number(all_ward_codes, "W")
    for w in wards:
        dept_item = dept_by_name.get(w.department) if w.department else None
        dept_note = f"department {w.department!r}" if w.department else "no department"
        if dept_item is not None and dept_item.action == "skip":
            plan.append(PlanItem("ward", w.name, "skip", detail=f"department {w.department!r} was skipped"))
            continue
        matches = db_wards.get(w.name, [])
        if len(matches) > 1:
            plan.append(PlanItem("ward", w.name, "skip", detail="more than one ward already has this exact name"))
        elif matches:
            set_phone, note = _phone_decision(matches[0].phone, w.phone, overwrite_phones)
            plan.append(PlanItem("ward", w.name, "exists", code=matches[0].code, phone=w.phone,
                                 detail=note, entity=matches[0], set_phone=set_phone))
        else:
            item = PlanItem("ward", w.name, "create", code=make_code("W", next_w), phone=w.phone, detail=dept_note)
            item.entity = dept_item  # resolved to an id at apply time
            next_w += 1
            plan.append(item)

    # ---- categories
    existing_cats: dict[str, EquipmentCategory] = {c.name.strip(): c for c in (await db.execute(select(EquipmentCategory))).scalars().all()}
    for name in categories:
        plan.append(PlanItem("category", name, "exists" if name in existing_cats else "create"))
    return plan


def format_plan(plan: list[PlanItem]) -> str:
    lines = []
    for kind in ("department", "ward", "category"):
        items = [p for p in plan if p.kind == kind]
        lines.append(f"--- {kind}s ({len(items)}) ---")
        for p in items:
            bits = [f"{p.action.upper():6}", p.code or "-".ljust(4), repr(p.name)]
            if p.phone:
                bits.append(f"phone={p.phone}")
            if p.detail:
                bits.append(f"[{p.detail}]")
            lines.append("  " + " ".join(bits))
    counts: dict[str, int] = {}
    for p in plan:
        key = f"{p.kind}:{p.action}"
        counts[key] = counts.get(key, 0) + 1
        if p.set_phone:
            counts[f"{p.kind}:phone_set"] = counts.get(f"{p.kind}:phone_set", 0) + 1
    lines.append("Summary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return "\n".join(lines)


async def apply_plan(db, plan: list[PlanItem], *, overwrite_phones: bool) -> dict:
    """Writes the plan inside the caller's transaction (no commit here)."""
    created: dict[str, list] = {"departments": [], "wards": [], "categories": []}
    phones_changed: list[dict] = []
    dept_ids: dict[str, object] = {}
    for p in plan:
        if p.kind == "department" and p.action == "exists":
            dept_ids[p.name] = p.entity.id
    for p in plan:
        if p.action == "skip":
            continue
        if p.action == "exists":
            if p.set_phone:
                phones_changed.append({"entity": p.kind, "id": str(p.entity.id), "before": p.entity.phone, "after": p.set_phone})
                p.entity.phone = p.set_phone
            continue
        if p.kind == "department":
            obj = Department(code=p.code, name=p.name, phone=p.phone)
            db.add(obj)
            await db.flush()
            dept_ids[p.name] = obj.id
            created["departments"].append({"id": str(obj.id), "code": p.code, "name": p.name, "phone": p.phone})
        elif p.kind == "ward":
            dept_item = p.entity
            dept_id = dept_ids.get(dept_item.name) if dept_item is not None else None
            obj = Ward(code=p.code, name=p.name, department_id=dept_id, phone=p.phone)
            db.add(obj)
            await db.flush()
            created["wards"].append({"id": str(obj.id), "code": p.code, "name": p.name, "phone": p.phone,
                                     "department_id": str(dept_id) if dept_id else None})
        else:
            obj = EquipmentCategory(name=p.name)
            db.add(obj)
            await db.flush()
            created["categories"].append({"id": str(obj.id), "name": p.name})
    await db.flush()
    after = {"kind": "master_data_load", "overwrite_phones": overwrite_phones, "created": created,
             "phones_changed": phones_changed}
    if not (any(created.values()) or phones_changed):
        return after  # nothing changed: no audit noise on a no-op re-run
    await record_audit_event(db, actor_user_id=None, action=AUDIT_ACTION_IMPORT,
                             entity_type=AUDIT_ENTITY_WARD, entity_id=None, after=after)
    return after


async def run(wards_path: Path, categories_path: Path, *, apply: bool, overwrite_phones: bool, out=print) -> int:
    try:
        wards = parse_wards(wards_path)
        categories = parse_categories(categories_path)
    except InputError as exc:
        out("INPUT ERRORS (nothing was written):")
        for e in exc.errors:
            out(f"  - {e}")
        return 2
    async with AsyncSessionLocal() as db:
        plan = await build_plan(db, wards, categories, overwrite_phones=overwrite_phones)
        out(format_plan(plan))
        if not apply:
            out("DRY RUN: nothing was written. Re-run with --apply to write this plan.")
            return 0
        try:
            await apply_plan(db, plan, overwrite_phones=overwrite_phones)
            await db.commit()
        except Exception as exc:  # whole load is one transaction
            await db.rollback()
            out(f"APPLY FAILED, nothing was written: {type(exc).__name__}: {exc}")
            return 1
    out("APPLIED: all rows written in one transaction with one audit entry.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--wards", required=True, type=Path)
    parser.add_argument("--categories", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="write the plan (default is a dry run)")
    parser.add_argument("--overwrite-phones", action="store_true", help="replace non-empty phones on existing rows")
    args = parser.parse_args(argv)
    return asyncio.run(run(args.wards, args.categories, apply=args.apply, overwrite_phones=args.overwrite_phones))


if __name__ == "__main__":
    raise SystemExit(main())
