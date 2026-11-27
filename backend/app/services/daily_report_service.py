"""Roadmap PR30 (Owner Governance 2026-11-25 D5/D6): daily shift report data.

Read-only. Builds the event list and aggregates behind the daily summary
workbook and the printable daily forms from existing dispatch/receipt rows;
nothing here writes, and nothing is stored (the attributed shift is computed
at report time only, D6). No patient identifier is read or emitted.

Report date ``D`` = the Night shift that started at 20:00 on ``D-1`` plus the
Day shift ``D`` 08:00-20:00 (Asia/Bangkok).

D6 attribution: for a boundary B (08:00 or 20:00), an event keyed within
+/-``grace_minutes`` of B (``[B-grace, B+grace)``; 0 = strict clock cut) is
attributed to whichever of the two shift instances adjacent to B the keying
operator predominantly worked, i.e. the one with more of that operator's events
*outside every window*. Ties, or an operator with no such events, fall back to
the clock rule. "That business day" is read as the two shift instances that
meet at B (the only ones the boundary can move an event between).
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.exceptions import ExportTooLargeError, InvalidInputError
from app.core.reporting_time import Shift
from app.models.equipment import Equipment
from app.models.master_data import Department, EquipmentCategory, Ward
from app.models.report_mapping import ReportWardRow
from app.models.transaction import BorrowTransaction
from app.models.user import User
from app.schemas.checklist import report_columns
from app.services.report_export_service import MAX_EXPORT_ROWS
from app.services.system_notes import operator_note

_BKK = ZoneInfo("Asia/Bangkok")

DEFAULT_GRACE_MINUTES = 60
MAX_GRACE_MINUTES = 240  # a boundary window may never reach the next boundary's window
UNSPECIFIED_LABEL = "(ไม่ระบุ)"

_DAY_START = time(8, 0)
_NIGHT_START = time(20, 0)

_THAI_SHIFT = {Shift.NIGHT: "กะดึก", Shift.DAY: "กะเช้า"}
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# Rows per printed page of the daily form (the company form has 33 data rows).
FORM_ROWS_PER_PAGE = 33

# Equipment roles used by the Owner's report layout. Categories are free-text
# master data, so a role is recognised by name; anything else keeps its own
# name as an extra row.
ROLE_INFUSION = "infusion"
ROLE_PCA = "pca"
ROLE_SYRINGE = "syringe"
ROLE_MATTRESS = "mattress"
ROLE_CRYO = "cryo"
ROLE_BED = "bed"
ROLE_PNEUMATIC = "pneumatic"
ROLE_RESPIRATOR = "respirator"
_ROLE_PATTERNS = (
    (ROLE_PCA, re.compile(r"\bpca\b", re.I)),
    (ROLE_SYRINGE, re.compile(r"syringe", re.I)),
    (ROLE_INFUSION, re.compile(r"infusion", re.I)),
    (ROLE_MATTRESS, re.compile(r"mattress", re.I)),
    (ROLE_CRYO, re.compile(r"cryo", re.I)),
    (ROLE_BED, re.compile(r"bed\s*(exit|alarm|alrm)|occupancy", re.I)),
    (ROLE_PNEUMATIC, re.compile(r"pneumatic", re.I)),
    (ROLE_RESPIRATOR, re.compile(r"respirator|ventilator", re.I)),
)


def category_role(name: str | None) -> str | None:
    for role, pattern in _ROLE_PATTERNS:
        if pattern.search(name or ""):
            return role
    return None


# Department / ward layout of sheet "รายงาน": (dispense mode, [(treatment type,
# fill colour, [layout slot labels])]). Each real ward is matched to a slot
# (admin short label, ward name or name prefix) and printed as its OWN row
# inside the slot (D18: never merged); wards outside the layout go to an
# "อื่น ๆ" block so no count is lost.
WARD_LAYOUT: list[tuple[str, list[tuple[str, str, list[str]]]]] = [
    (
        "Standby support",
        [
            ("IPD ตึก A", "92D050", ["Ward 5", "Ward 6", "Ward 7", "Ward 8", "Ward 9", "Ward 10", "Ward 11"]),
            ("IPD ตึก B", "FFCCFF", ["W4B", "W5B", "W6B", "ICU3", "ICU4"]),
            ("Clinical Care", "FFFF00", ["RR", "OR", "ICU1", "ICU2  CCU", "ER"]),
        ],
    ),
    (
        "After request",
        [
            (
                "OPD",
                "F8CBAD",
                [
                    "Pediatrics Clinic", "OB", "Oncology Clinic", "Cath Lab", "Internal Medicine Clinic",
                    "Hemodialysis Clinic", "Gastroenterology Clinic", "Pre Surgery", "Surgery +Ortho", "X-Ray",
                    "Training", "LR", "Nursery", "Heart Clinic", "Skin", "Eye", "ENT", "Wellness", "Neuro", "ARI",
                ],
            ),
        ],
    ),
]
# Rows the Owner's file shades grey across the count columns.
SHADED_ROWS = {"Ward 6", "Ward 11", "OR", "ICU1", "ICU2  CCU"}


# Short "ชนิดเครื่อง" sheet names and the form "หมายเหตุ" labels (Owner's tool).
ROLE_SHORT_NAMES = {
    ROLE_INFUSION: "Infusion Pump",
    ROLE_PCA: "PCA",
    ROLE_SYRINGE: "Syringe Pump",
    ROLE_MATTRESS: "Air Mattress",
    ROLE_CRYO: "Cryo cuff",
    ROLE_BED: "Bed Alarm",
    ROLE_PNEUMATIC: "Pneumatic Pump",
    ROLE_RESPIRATOR: "Respirator",
}
ROLE_ORDER = tuple(ROLE_SHORT_NAMES)
OTHER_LABEL = "อื่น ๆ"
OTHER_COLOR = "D9D9D9"
FORM_NOTE_LABELS = {ROLE_BED: "Bed Alarms", ROLE_PNEUMATIC: "PNEUMATIC PUMP"}


def format_date(d: date) -> str:
    """dd/Mon/yyyy (Gregorian, English month abbreviation) as in the Owner's files."""
    return f"{d.day:02d}/{_MONTHS[d.month - 1]}/{d.year}"


def validate_grace(grace_minutes: int) -> int:
    if not 0 <= grace_minutes <= MAX_GRACE_MINUTES:
        raise InvalidInputError(f"'grace_minutes' must be between 0 and {MAX_GRACE_MINUTES}")
    return grace_minutes


# --------------------------------------------------------------------------
# Shift windows and D6 attribution (pure functions)
# --------------------------------------------------------------------------


def instance_start(local: datetime) -> datetime:
    """Start (naive local) of the shift instance containing ``local``."""
    t = local.time()
    if _DAY_START <= t < _NIGHT_START:
        return datetime.combine(local.date(), _DAY_START)
    if t >= _NIGHT_START:
        return datetime.combine(local.date(), _NIGHT_START)
    return datetime.combine(local.date() - timedelta(days=1), _NIGHT_START)


def instance_shift(start: datetime) -> Shift:
    return Shift.DAY if start.time() == _DAY_START else Shift.NIGHT


def report_instances(report_date: date) -> dict[datetime, Shift]:
    """The two shift instances that make up report date ``D``."""
    night = datetime.combine(report_date - timedelta(days=1), _NIGHT_START)
    day = datetime.combine(report_date, _DAY_START)
    return {night: Shift.NIGHT, day: Shift.DAY}


def fetch_window_utc(report_date: date) -> tuple[datetime, datetime]:
    """UTC range [Day(D-1) start, Night(D) end): every instance adjacent to a
    boundary inside the report, so attribution can see both neighbours."""
    start_local = datetime.combine(report_date - timedelta(days=1), _DAY_START, tzinfo=_BKK)
    end_local = datetime.combine(report_date + timedelta(days=1), _DAY_START, tzinfo=_BKK)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _nearest_boundary(local: datetime) -> datetime:
    candidates = []
    for offset in (-1, 0, 1):
        d = local.date() + timedelta(days=offset)
        candidates.append(datetime.combine(d, _DAY_START))
        candidates.append(datetime.combine(d, _NIGHT_START))
    return min(candidates, key=lambda b: abs(b - local))


def window_boundary(local: datetime, grace_minutes: int) -> datetime | None:
    """The boundary whose grace window contains ``local``, else None."""
    if grace_minutes <= 0:
        return None
    boundary = _nearest_boundary(local)
    grace = timedelta(minutes=grace_minutes)
    if boundary - grace <= local < boundary + grace:
        return boundary
    return None


@dataclass
class DailyEvent:
    kind: str  # "dispatch" | "receipt"
    at: datetime  # aware UTC
    local: datetime  # naive Asia/Bangkok
    operator_id: uuid.UUID | None
    operator_name: str
    transaction_id: uuid.UUID
    bcm_code: str
    category_name: str
    ward_id: uuid.UUID | None
    ward_name: str
    contact_name: str | None
    checks: dict[str, bool | None]
    notes: str | None
    # Roadmap PR33 (D14): "pool" | "demo" | "loan"; shown as a text badge.
    source: str = "pool"
    clock_shift: Shift = Shift.DAY
    instance: datetime = field(default_factory=datetime.now)
    shift: Shift = Shift.DAY
    row_label: str = ""
    form_position: str = ""


def attribute_shifts(events: list[DailyEvent], grace_minutes: int) -> None:
    """D6: sets ``instance``/``shift`` on every event (in place). Pure."""
    for e in events:
        e.instance = instance_start(e.local)
        e.clock_shift = instance_shift(e.instance)
        e.shift = e.clock_shift

    windows = {id(e): window_boundary(e.local, grace_minutes) for e in events}

    # operator -> instance start -> count of that operator's events outside every window
    counts: dict[uuid.UUID, dict[datetime, int]] = {}
    for e in events:
        if windows[id(e)] is None and e.operator_id is not None:
            per_instance = counts.setdefault(e.operator_id, {})
            per_instance[e.instance] = per_instance.get(e.instance, 0) + 1

    for e in events:
        boundary = windows[id(e)]
        if boundary is None or e.operator_id is None:
            continue
        before = instance_start(boundary - timedelta(seconds=1))
        after = boundary
        per_instance = counts.get(e.operator_id, {})
        n_before, n_after = per_instance.get(before, 0), per_instance.get(after, 0)
        if n_before > n_after:
            e.instance = before
        elif n_after > n_before:
            e.instance = after
        # tie / no other events: clock rule (already set)
        e.shift = instance_shift(e.instance)


# --------------------------------------------------------------------------
# Ward -> report row mapping (admin-editable overrides; defaults from master data)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class WardMapping:
    ward_id: uuid.UUID | None
    ward_name: str
    department_name: str | None
    report_row_label: str
    treatment_type: str
    dispense_mode: str
    sort_order: int
    is_override: bool


def effective_mapping(ward: Ward, department: Department | None, override: ReportWardRow | None) -> WardMapping:
    """Default: report row = ward name, treatment type = department name,
    dispense mode blank, order 0. An override row replaces any set field."""
    dept_name = department.name if department is not None else None
    return WardMapping(
        ward_id=ward.id,
        ward_name=ward.name,
        department_name=dept_name,
        report_row_label=(override.report_row_label if override and override.report_row_label else ward.name),
        treatment_type=(override.treatment_type if override and override.treatment_type else (dept_name or "")),
        dispense_mode=(override.dispense_mode if override and override.dispense_mode else ""),
        sort_order=override.sort_order if override else 0,
        is_override=override is not None,
    )


async def load_ward_mappings(db: AsyncSession) -> dict[uuid.UUID, WardMapping]:
    rows = (
        await db.execute(
            select(Ward, Department, ReportWardRow)
            .outerjoin(Department, Department.id == Ward.department_id)
            .outerjoin(ReportWardRow, ReportWardRow.ward_id == Ward.id)
            .order_by(Ward.name)
        )
    ).all()
    return {w.id: effective_mapping(w, d, o) for w, d, o in rows}



# --------------------------------------------------------------------------
# D18: one report row per ward, grouped/ordered by the Owner's layout
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class WardRow:
    """One row of the Excel ward table / Standby summary. ``ward_id`` is None
    for a layout slot that no ward maps to yet, for "(ไม่ระบุ)" and for a
    stored-edit label whose ward no longer exists."""

    label: str
    mode: str
    treatment: str
    color: str
    ward_id: uuid.UUID | None = None
    shaded: bool = False
    # Admin-mapped, or otherwise worth listing in the LINE text even at zero.
    listed: bool = False
    sort_order: int = 10**6


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().casefold()


def _layout_slots() -> list[tuple[str, str, str, str]]:
    return [
        (mode, treatment, color, label)
        for mode, groups in WARD_LAYOUT
        for treatment, color, labels in groups
        for label in labels
    ]


def _slot_key(text: str) -> str:
    """Matching key: case-insensitive, spaces/dots/hyphens removed, leading
    "WARD" folded to "W" ("Ward 6 B", "Ward6B", "W6B" -> "w6b")."""
    key = re.sub(r"[\s.\-]+", "", text or "").casefold()
    return "w" + key[4:] if key.startswith("ward") else key


def _match_slot(m: WardMapping, slots: list[tuple[str, str, str, str]]) -> int | None:
    """Layout slot of a ward, by normalised name (admin short label first, then
    ward name): exact match first; then slot "Ward N" takes only "Ward N" /
    "Ward NA" (never a B or other letter suffix, never extra digits, so a
    "Ward NB" without a W{N}B slot goes to "อื่น ๆ"); other slots match by
    label prefix on the original name with a word boundary."""
    originals = [m.report_row_label or "", m.ward_name or ""]
    candidates = [_slot_key(o) for o in originals]
    norms = [_slot_key(s[3]) for s in slots]
    for cand in candidates:
        if cand in norms:
            return norms.index(cand)
    for cand, orig in zip(candidates, originals):
        best: int | None = None
        for i, n in enumerate(norms):
            if re.fullmatch(r"w\d+", n):
                ok = cand == n + "a"
            else:
                # Word boundary on the original name: the slot label must be
                # followed by end/space/punctuation, never a letter or digit
                # ("OR 2" -> OR, but "Orthopedic Unit" is not OR).
                words = r"\s+".join(re.escape(w) for w in slots[i][3].split())
                ok = re.match(words + r"(?!\w)", orig.strip(), re.I) is not None
            if ok and (best is None or len(n) > len(norms[best])):
                best = i
        if best is not None:
            return best
    return None


def ward_row_labels(mappings: dict[uuid.UUID, WardMapping]) -> dict[uuid.UUID, str]:
    """Unique display label per ward: the admin short label when only this ward
    uses it, otherwise the ward's own name (so 7A and 7B never share "Ward 7")."""
    ordered = sorted(mappings.values(), key=lambda m: (m.sort_order, m.ward_name, str(m.ward_id)))
    use: dict[str, int] = {}
    for m in ordered:
        use[_norm(m.report_row_label)] = use.get(_norm(m.report_row_label), 0) + 1
    labels: dict[uuid.UUID, str] = {}
    taken: set[str] = set()
    for m in ordered:
        base = m.report_row_label if use[_norm(m.report_row_label)] == 1 else m.ward_name
        label, n = base, 2
        while _norm(label) in taken:
            label = f"{base} ({n})"
            n += 1
        taken.add(_norm(label))
        labels[m.ward_id] = label
    return labels


def build_ward_rows(
    mappings: dict[uuid.UUID, WardMapping],
    relevant_ward_ids: set[uuid.UUID],
    extra_labels: list[str] | tuple[str, ...] = (),
) -> list[WardRow]:
    """Rows in layout order. Every ward matching a layout slot is its own row
    inside that slot (a slot no ward matches stays as an empty placeholder row).
    Wards outside the layout go to "อื่น ๆ" only when admin-mapped or listed in
    ``relevant_ward_ids`` (activity / standby); ``extra_labels`` appends ward-less
    rows (e.g. unspecified, stored edits). Counts stay lossless: callers put every
    event's ward in ``relevant_ward_ids``."""
    slots = _layout_slots()
    labels = ward_row_labels(mappings)
    by_slot: dict[int, list[WardMapping]] = {}
    others: list[WardMapping] = []
    for m in mappings.values():
        idx = _match_slot(m, slots)
        if idx is not None:
            by_slot.setdefault(idx, []).append(m)
        elif m.is_override or m.ward_id in relevant_ward_ids:
            others.append(m)
    rows: list[WardRow] = []
    for i, (mode, treatment, color, slot_label) in enumerate(slots):
        shaded = slot_label in SHADED_ROWS
        wards = sorted(by_slot.get(i, []), key=lambda m: (m.sort_order, m.ward_name, str(m.ward_id)))
        if not wards:
            rows.append(WardRow(slot_label, mode, treatment, color, None, shaded, False))
        for m in wards:
            rows.append(WardRow(labels[m.ward_id], mode, treatment, color, m.ward_id, shaded, m.is_override, m.sort_order))
    for m in sorted(others, key=lambda m: (m.sort_order, labels[m.ward_id], str(m.ward_id))):
        rows.append(WardRow(labels[m.ward_id], OTHER_LABEL, OTHER_LABEL, OTHER_COLOR, m.ward_id, False, m.is_override, m.sort_order))
    seen = {_norm(r.label) for r in rows}
    for label in extra_labels:
        if _norm(label) not in seen:
            seen.add(_norm(label))
            rows.append(WardRow(label, OTHER_LABEL, OTHER_LABEL, OTHER_COLOR, None, False, True))
    return rows


# --------------------------------------------------------------------------
# Loading and aggregation
# --------------------------------------------------------------------------


@dataclass
class Counts:
    night_dispatch: int = 0
    night_receipt: int = 0
    day_dispatch: int = 0
    day_receipt: int = 0

    def add(self, event: DailyEvent) -> None:
        attr = f"{'night' if event.shift == Shift.NIGHT else 'day'}_{event.kind}"
        setattr(self, attr, getattr(self, attr) + 1)

    @property
    def total_dispatch(self) -> int:
        return self.night_dispatch + self.day_dispatch

    @property
    def total_receipt(self) -> int:
        return self.night_receipt + self.day_receipt

    @property
    def total(self) -> int:
        return self.total_dispatch + self.total_receipt


@dataclass
class DailyReport:
    report_date: date
    grace_minutes: int
    events: list[DailyEvent]  # in-report events, time-ordered
    ward_rows: list["WardRow"]  # D18: one row per ward, in the Owner's layout order
    categories: list[tuple[str, Counts]]
    operators: list[tuple[str, Counts]]
    totals: Counts
    # Equipment in the pool per role (e.g. Cryo cuff total shown on the sheet).
    pool_counts: dict[str, int] = field(default_factory=dict)


def _stamp_form_positions(events: list[DailyEvent], report_date: date) -> None:
    """Owner's wording: "แบบบันทึกส่งเครื่อง[เมื่อวาน] แถว N" -- N counts the rows
    of that kind on the printed form the event lands on. Forms are per (shift,
    form date, kind) exactly as `daily_report_forms_service._form_groups` splits
    them, FORM_ROWS_PER_PAGE rows per page; a form of more than one page adds
    "หน้า P" ("แถว" restarts at 1 on every page)."""
    groups: dict[tuple[Shift, date, str], list[DailyEvent]] = {}
    for e in events:
        groups.setdefault((e.shift, e.local.date(), e.kind), []).append(e)
    for (_shift, form_date, kind), rows in groups.items():
        yesterday = "เมื่อวาน" if form_date < report_date else ""
        paged = len(rows) > FORM_ROWS_PER_PAGE
        for i, e in enumerate(rows):
            page, row = divmod(i, FORM_ROWS_PER_PAGE)
            where = f"หน้า {page + 1} แถว {row + 1}" if paged else f"แถว {row + 1}"
            e.form_position = f"แบบบันทึก{'ส่ง' if kind == 'dispatch' else 'รับ'}เครื่อง{yesterday} {where}"


async def _load_events(db: AsyncSession, start: datetime, end: datetime) -> list[DailyEvent]:
    tx = BorrowTransaction
    op = aliased(User)
    events: list[DailyEvent] = []
    for kind in ("dispatch", "receipt"):
        at_col = tx.borrowed_at if kind == "dispatch" else tx.returned_at
        op_col = tx.borrower_user_id if kind == "dispatch" else tx.received_by_user_id
        stmt = (
            select(tx, Equipment.bcm_code, EquipmentCategory.name, Ward.name, op.full_name, Equipment.equipment_source)
            .join(Equipment, Equipment.id == tx.equipment_id)
            .outerjoin(EquipmentCategory, EquipmentCategory.id == Equipment.category_id)
            .outerjoin(Ward, Ward.id == tx.ward_id)
            .outerjoin(op, op.id == op_col)
            .where(at_col.is_not(None), at_col >= start, at_col < end)
            .order_by(at_col, tx.id)
            .limit(MAX_EXPORT_ROWS + 1)
        )
        rows = (await db.execute(stmt)).all()
        for t, bcm, cat_name, ward_name, op_name, source in rows:
            at = t.borrowed_at if kind == "dispatch" else t.returned_at
            try:
                checks = report_columns(t.dispatch_checks if kind == "dispatch" else t.receipt_checks)
            except Exception:  # malformed stored JSON must not break a report
                checks = {"screen": None, "charger": None, "clamp": None}
            events.append(
                DailyEvent(
                    kind=kind,
                    at=at,
                    local=at.astimezone(_BKK).replace(tzinfo=None),
                    operator_id=t.borrower_user_id if kind == "dispatch" else t.received_by_user_id,
                    operator_name=(t.dispatch_keyer_label if kind == "dispatch" else t.receipt_keyer_label) or op_name or UNSPECIFIED_LABEL,
                    transaction_id=t.id,
                    bcm_code=bcm or "",
                    source=source or "pool",
                    category_name=cat_name or UNSPECIFIED_LABEL,
                    ward_id=t.ward_id,
                    ward_name=ward_name or "",
                    contact_name=t.dispatch_contact_name if kind == "dispatch" else t.receipt_contact_name,
                    checks=checks,
                    # `notes` is one column; a receipt overwrites the dispatch note.
                    notes=operator_note(t.notes) if (kind == "receipt" or t.returned_at is None) else None,
                )
            )
        if len(rows) > MAX_EXPORT_ROWS:
            raise ExportTooLargeError("Too many events for one daily report")
    return events


async def _pool_counts(db: AsyncSession) -> dict[str, int]:
    rows = (
        await db.execute(
            select(EquipmentCategory.name, func.count(Equipment.id))
            .join(Equipment, Equipment.category_id == EquipmentCategory.id)
            .group_by(EquipmentCategory.name)
        )
    ).all()
    counts: dict[str, int] = {}
    for name, n in rows:
        role = category_role(name)
        if role:
            counts[role] = counts.get(role, 0) + n
    return counts


async def build_daily_report(db: AsyncSession, report_date: date, grace_minutes: int) -> DailyReport:
    grace_minutes = validate_grace(grace_minutes)
    start, end = fetch_window_utc(report_date)
    fetched = await _load_events(db, start, end)
    attribute_shifts(fetched, grace_minutes)

    instances = report_instances(report_date)
    events = sorted((e for e in fetched if e.instance in instances), key=lambda e: (e.at, e.kind, str(e.transaction_id)))
    if len(events) > MAX_EXPORT_ROWS:
        raise ExportTooLargeError("Too many events for one daily report")

    mappings = await load_ward_mappings(db)
    ward_rows = build_ward_rows(
        mappings,
        {e.ward_id for e in events if e.ward_id in mappings},
        [UNSPECIFIED_LABEL] if any(e.ward_id not in mappings for e in events) else [],
    )
    label_of = {r.ward_id: r.label for r in ward_rows if r.ward_id is not None}
    categories: dict[str, Counts] = {}
    operators: dict[str, Counts] = {}
    totals = Counts()
    for e in events:
        e.row_label = label_of.get(e.ward_id, UNSPECIFIED_LABEL)
        if not e.ward_name:
            e.ward_name = UNSPECIFIED_LABEL
        categories.setdefault(e.category_name, Counts()).add(e)
        operators.setdefault(e.operator_name, Counts()).add(e)
        totals.add(e)
    _stamp_form_positions(events, report_date)
    pool_counts = await _pool_counts(db)

    return DailyReport(
        report_date=report_date,
        grace_minutes=grace_minutes,
        events=events,
        ward_rows=ward_rows,
        categories=sorted(categories.items(), key=lambda kv: kv[0]),
        operators=sorted(operators.items(), key=lambda kv: kv[0]),
        totals=totals,
        pool_counts=pool_counts,
    )
