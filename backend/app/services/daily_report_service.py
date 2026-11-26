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

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
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

_BKK = ZoneInfo("Asia/Bangkok")

DEFAULT_GRACE_MINUTES = 60
MAX_GRACE_MINUTES = 240  # a boundary window may never reach the next boundary's window
UNSPECIFIED_LABEL = "(ไม่ระบุ)"

_DAY_START = time(8, 0)
_NIGHT_START = time(20, 0)

_THAI_SHIFT = {Shift.NIGHT: "กะดึก", Shift.DAY: "กะเช้า"}
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# Rows per printed page of the daily form; also drives the "position in form"
# column so the workbook can point at the exact printed row.
FORM_ROWS_PER_PAGE = 25


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


_UNMAPPED = WardMapping(None, UNSPECIFIED_LABEL, None, UNSPECIFIED_LABEL, "", "", 10**6, False)


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
class WardRowSummary:
    dispense_mode: str
    treatment_type: str
    label: str
    sort_order: int
    counts: Counts = field(default_factory=Counts)


@dataclass
class DailyReport:
    report_date: date
    grace_minutes: int
    events: list[DailyEvent]  # in-report events, time-ordered
    ward_rows: list[WardRowSummary]
    categories: list[tuple[str, Counts]]
    operators: list[tuple[str, Counts]]
    totals: Counts


def _stamp_form_positions(events: list[DailyEvent]) -> None:
    for kind in ("dispatch", "receipt"):
        for i, e in enumerate([x for x in events if x.kind == kind]):
            e.form_position = f"หน้า {i // FORM_ROWS_PER_PAGE + 1} แถว {i % FORM_ROWS_PER_PAGE + 1}"


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
                    operator_name=op_name or UNSPECIFIED_LABEL,
                    transaction_id=t.id,
                    bcm_code=bcm or "",
                    source=source or "pool",
                    category_name=cat_name or UNSPECIFIED_LABEL,
                    ward_id=t.ward_id,
                    ward_name=ward_name or "",
                    contact_name=t.dispatch_contact_name if kind == "dispatch" else t.receipt_contact_name,
                    checks=checks,
                    # `notes` is one column; a receipt overwrites the dispatch note.
                    notes=t.notes if (kind == "receipt" or t.returned_at is None) else None,
                )
            )
        if len(rows) > MAX_EXPORT_ROWS:
            raise ExportTooLargeError("Too many events for one daily report")
    return events


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
    ward_rows: dict[tuple[str, str, str], WardRowSummary] = {}
    categories: dict[str, Counts] = {}
    operators: dict[str, Counts] = {}
    totals = Counts()
    for e in events:
        m = mappings.get(e.ward_id, _UNMAPPED) if e.ward_id else _UNMAPPED
        e.row_label = m.report_row_label
        if not e.ward_name:
            e.ward_name = UNSPECIFIED_LABEL
        key = (m.dispense_mode, m.treatment_type, m.report_row_label)
        summary = ward_rows.get(key)
        if summary is None:
            summary = ward_rows[key] = WardRowSummary(*key[:2], key[2], m.sort_order)
        else:
            summary.sort_order = min(summary.sort_order, m.sort_order)
        summary.counts.add(e)
        categories.setdefault(e.category_name, Counts()).add(e)
        operators.setdefault(e.operator_name, Counts()).add(e)
        totals.add(e)
    _stamp_form_positions(events)

    return DailyReport(
        report_date=report_date,
        grace_minutes=grace_minutes,
        events=events,
        ward_rows=sorted(
            ward_rows.values(), key=lambda r: (r.sort_order, r.dispense_mode, r.treatment_type, r.label)
        ),
        categories=sorted(categories.items(), key=lambda kv: kv[0]),
        operators=sorted(operators.items(), key=lambda kv: kv[0]),
        totals=totals,
    )
