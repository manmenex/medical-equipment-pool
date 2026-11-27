"""Roadmap PR34 (Owner Governance 2026-11-26 D15/D16): the standby summary.

Read-mostly. Computes, for one (date, cut-off), the infusion-pump Standby
numbers per ward, the BME stock (devices / chargers / clamps / ready) and the
pneumatic-pump counts, then layers staff-edited override values on top
(system and edited values are both kept). Nothing here reads or emits an HN:
the only patient-related input is the ``has_hn`` indicator (and, for an HN
added later, the instant it was added, ``hn_added_at``).

Time model (Asia/Bangkok): the summary ``date`` is a PR30 report date D.
``night`` = 08:00 on D (end of the Night shift that began 20:00 on D-1),
``day`` = 20:00 on D (end of Day shift D). The "business day" used for
"returned today" is the PR30 report day: from 20:00 on D-1 up to the cut-off.
Boundaries are strict clock times (no D6 grace attribution here).

Reconstruction as of the cut-off (past dates work from stored timestamps):

- A transaction is *open at the cut-off* when it was dispatched at or before the
  cut-off and was not received at or before it. A transaction closed by
  re-dispatch (no receipt) ended when the next dispatch of the same equipment
  began.
- A dispatch is *Standby* at the cut-off when it was open and had no HN then:
  ``has_hn`` is false, or the HN was added after the cut-off (``hn_added_at``).
- BME devices at pool = equipment of the infusion category that is not open at
  the cut-off. APPROXIMATION: equipment status history is not stored, so
  equipment that is currently ``unavailable_defective`` / ``decommissioned`` /
  soft-deleted / returned to owner is excluded, and equipment created after the
  cut-off is excluded; a device that was defective at the cut-off but has since
  been repaired is counted as at pool.
- Chargers / clamps at pool = staff baseline (with the instant it was set) +
  receipts with that item checked - dispatches with that item checked, between
  the baseline instant (exclusive) and the cut-off (inclusive). A NULL
  (unrecorded) check counts as present. Approximate by nature (manual
  correction expected); not available (None) before a baseline exists or when
  the cut-off precedes it.
- Ready = min(devices, chargers, clamps) of the *effective* component values.
"""
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import (
    AUDIT_ACTION_CREATE,
    AUDIT_ACTION_DELETE,
    AUDIT_ACTION_UPDATE,
    AUDIT_ENTITY_STANDBY_CONFIG,
    AUDIT_ENTITY_STANDBY_OVERRIDE,
    record_audit_event,
)
from app.core.exceptions import InvalidInputError, ResourceNotFoundError
from app.models.equipment import Equipment, EquipmentStatus
from app.models.master_data import EquipmentCategory
from app.models.standby_summary import (
    CUTOFFS,
    ROLE_INFUSION,
    ROLE_PNEUMATIC,
    STANDBY_ROLES,
    StandbySummaryConfig,
    StandbySummaryOverride,
)
from app.models.transaction import BorrowTransaction, TransactionStatus
from app.schemas.checklist import report_columns
from app.services import daily_report_service

_BKK = ZoneInfo("Asia/Bangkok")
_CUTOFF_TIME = {"night": time(8, 0), "day": time(20, 0)}
_DAY_START_LOCAL = time(20, 0)  # PR30 report day starts at 20:00 on D-1

NAME_PATTERNS = {ROLE_INFUSION: re.compile("infusion", re.I), ROLE_PNEUMATIC: re.compile("pneumatic", re.I)}

KEY_BME_DEVICES = "bme_devices"
KEY_CHARGERS = "chargers"
KEY_CLAMPS = "clamps"
KEY_READY = "ready"
KEY_PNEUMATIC_IN_USE = "pneumatic_in_use"
KEY_PNEUMATIC_RETURNED = "pneumatic_returned"
INFUSION_FIXED_KEYS = (KEY_BME_DEVICES, KEY_CHARGERS, KEY_CLAMPS, KEY_READY)
PNEUMATIC_KEYS = (KEY_PNEUMATIC_IN_USE, KEY_PNEUMATIC_RETURNED)
WARD_KEY_PREFIX = "ward:"
MAX_OVERRIDE_VALUE = 9999

APPROXIMATIONS = [
    "จำนวนเครื่อง/สายชาร์จ/Clamp ที่คลังเป็นค่าประมาณ (คำนวณจาก baseline และรายการเช็กตอนส่ง/รับ) แก้ไขเองได้",
    "สถานะเครื่องย้อนหลังไม่ได้เก็บ: เครื่องที่ชำรุดหรือปลดระวางในปัจจุบันจะไม่ถูกนับ",
]


# --------------------------------------------------------------------------
# Time windows (pure)
# --------------------------------------------------------------------------


def validate_cutoff(cutoff: str) -> str:
    if cutoff not in CUTOFFS:
        raise InvalidInputError("'cutoff' must be 'night' or 'day'")
    return cutoff


def cutoff_instant(summary_date: date, cutoff: str) -> datetime:
    """Aware UTC instant of the cut-off: night = 08:00, day = 20:00 Asia/Bangkok on the date."""
    validate_cutoff(cutoff)
    return datetime.combine(summary_date, _CUTOFF_TIME[cutoff], tzinfo=_BKK).astimezone(timezone.utc)


def business_day_start(summary_date: date) -> datetime:
    """Aware UTC start of the summary's business day (PR30 report day): 20:00 on D-1."""
    return datetime.combine(summary_date - timedelta(days=1), _DAY_START_LOCAL, tzinfo=_BKK).astimezone(timezone.utc)


def ward_key(label: str) -> str:
    return f"{WARD_KEY_PREFIX}{label}"


def section_for_key(field_key: str) -> str:
    if field_key in PNEUMATIC_KEYS:
        return ROLE_PNEUMATIC
    if field_key in INFUSION_FIXED_KEYS:
        return ROLE_INFUSION
    if field_key.startswith(WARD_KEY_PREFIX) and 0 < len(field_key) - len(WARD_KEY_PREFIX) <= 100:
        return ROLE_INFUSION
    raise InvalidInputError("Unknown standby summary field_key")


# --------------------------------------------------------------------------
# Values
# --------------------------------------------------------------------------


@dataclass
class FieldValue:
    key: str
    label: str
    system_value: int | None
    override_value: int | None = None
    # Ward rows only: the Owner's report layout grouping (รูปแบบการจ่ายเครื่อง / ประเภทการรักษา).
    mode: str | None = None
    treatment: str | None = None
    # Ward rows only: shown in the LINE copy text (admin-mapped, standby or edited).
    in_text: bool = True
    text_order: int = 10**6
    text_label: str = ""

    @property
    def effective_value(self) -> int | None:
        return self.override_value if self.override_value is not None else self.system_value


@dataclass
class Baseline:
    chargers: int | None
    clamps: int | None
    set_at: datetime | None


@dataclass
class StandbySummary:
    summary_date: date
    cutoff: str
    cutoff_at: datetime
    business_day_start: datetime
    infusion_categories: list[str]
    pneumatic_categories: list[str]
    wards: list[FieldValue]
    bme_devices: FieldValue
    chargers: FieldValue
    clamps: FieldValue
    ready: FieldValue
    baseline: Baseline
    pneumatic_in_use: FieldValue
    pneumatic_returned: FieldValue


# --------------------------------------------------------------------------
# Category / config resolution
# --------------------------------------------------------------------------


async def get_config(db: AsyncSession, role: str) -> StandbySummaryConfig | None:
    return (
        await db.execute(select(StandbySummaryConfig).where(StandbySummaryConfig.category_role == role))
    ).scalar_one_or_none()


async def resolve_categories(db: AsyncSession, role: str) -> list[EquipmentCategory]:
    """The explicit category of the role's config, else every category whose
    name matches the role's default pattern (/infusion/i, /pneumatic/i)."""
    cfg = await get_config(db, role)
    if cfg is not None and cfg.category_id is not None:
        cat = await db.get(EquipmentCategory, cfg.category_id)
        return [cat] if cat is not None else []
    cats = (await db.execute(select(EquipmentCategory).order_by(EquipmentCategory.name))).scalars().all()
    return [c for c in cats if NAME_PATTERNS[role].search(c.name)]


def _present(checks: dict | None, item: str) -> bool:
    """A recorded check counts as absent only when explicitly False; NULL
    (not recorded) or unreadable counts as present."""
    try:
        return report_columns(checks)[item] is not False
    except Exception:
        return True


# --------------------------------------------------------------------------
# Reconstruction
# --------------------------------------------------------------------------


@dataclass
class _Tx:
    id: uuid.UUID
    equipment_id: uuid.UUID
    borrowed_at: datetime
    returned_at: datetime | None
    status: TransactionStatus
    close_reason: str | None
    ward_id: uuid.UUID | None
    has_hn: bool
    hn_added_at: datetime | None


async def _open_at_cutoff(db: AsyncSession, equipment_ids: set[uuid.UUID], cutoff_at: datetime) -> list[_Tx]:
    """Transactions of the given equipment that were open at the cut-off."""
    if not equipment_ids:
        return []
    tx = BorrowTransaction
    rows = (
        await db.execute(
            select(
                tx.id,
                tx.equipment_id,
                tx.borrowed_at,
                tx.returned_at,
                tx.status,
                tx.close_reason,
                tx.ward_id,
                tx.has_hn,
                tx.hn_added_at,
            )
            .where(tx.equipment_id.in_(equipment_ids), tx.borrowed_at <= cutoff_at)
            .order_by(tx.equipment_id, tx.borrowed_at, tx.id)
        )
    ).all()
    by_equipment: dict[uuid.UUID, list[_Tx]] = {}
    for r in rows:
        by_equipment.setdefault(r.equipment_id, []).append(_Tx(*r))
    open_txs: list[_Tx] = []
    for txs in by_equipment.values():
        for i, t in enumerate(txs):
            if t.returned_at is not None:
                is_open = t.returned_at > cutoff_at
            elif t.status == TransactionStatus.OPEN:
                is_open = True
            else:
                # Closed without a receipt (re-dispatch): ended when the next
                # dispatch of the same equipment began; if that dispatch is
                # after the cut-off it was still open at the cut-off.
                is_open = i == len(txs) - 1 and t.close_reason is not None
            if is_open:
                open_txs.append(t)
    return open_txs


def _no_hn_at(t: _Tx, cutoff_at: datetime) -> bool:
    return (not t.has_hn) or (t.hn_added_at is not None and t.hn_added_at > cutoff_at)


async def _category_equipment(db: AsyncSession, categories: list[EquipmentCategory]) -> list[Equipment]:
    if not categories:
        return []
    rows = (
        await db.execute(
            select(Equipment).where(
                Equipment.category_id.in_([c.id for c in categories]), Equipment.deleted_at.is_(None)
            )
        )
    ).scalars().all()
    # Roadmap PR33 (D14): devices returned to their owner leave all counts.
    return [e for e in rows if e.returned_to_owner_at is None]


async def _stock_delta(
    db: AsyncSession, categories: list[EquipmentCategory], after: datetime, cutoff_at: datetime
) -> tuple[int, int]:
    """(chargers, clamps) net change at the pool in (after, cutoff_at]."""
    if not categories:
        return 0, 0
    tx = BorrowTransaction
    ids = [c.id for c in categories]
    out = {"charger": 0, "clamp": 0}
    dispatches = (
        await db.execute(
            select(tx.dispatch_checks)
            .join(Equipment, Equipment.id == tx.equipment_id)
            .where(Equipment.category_id.in_(ids), tx.borrowed_at > after, tx.borrowed_at <= cutoff_at)
        )
    ).all()
    receipts = (
        await db.execute(
            select(tx.receipt_checks)
            .join(Equipment, Equipment.id == tx.equipment_id)
            .where(
                Equipment.category_id.in_(ids),
                tx.returned_at.is_not(None),
                tx.returned_at > after,
                tx.returned_at <= cutoff_at,
            )
        )
    ).all()
    for (checks,) in dispatches:
        for item in out:
            if _present(checks, item):
                out[item] -= 1
    for (checks,) in receipts:
        for item in out:
            if _present(checks, item):
                out[item] += 1
    return out["charger"], out["clamp"]


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------


async def _overrides(db: AsyncSession, summary_date: date, cutoff: str) -> dict[str, int]:
    rows = (
        await db.execute(
            select(StandbySummaryOverride).where(
                StandbySummaryOverride.summary_date == summary_date, StandbySummaryOverride.cutoff == cutoff
            )
        )
    ).scalars().all()
    return {r.field_key: r.value for r in rows}


async def build_summary(db: AsyncSession, summary_date: date, cutoff: str) -> StandbySummary:
    validate_cutoff(cutoff)
    cutoff_at = cutoff_instant(summary_date, cutoff)
    day_start = business_day_start(summary_date)
    overrides = await _overrides(db, summary_date, cutoff)

    infusion_cats = await resolve_categories(db, ROLE_INFUSION)
    pneumatic_cats = await resolve_categories(db, ROLE_PNEUMATIC)

    # ---- infusion pump
    equipment = await _category_equipment(db, infusion_cats)
    open_txs = await _open_at_cutoff(db, {e.id for e in equipment}, cutoff_at)
    open_equipment_ids = {t.equipment_id for t in open_txs}
    mappings = await daily_report_service.load_ward_mappings(db)

    # D18: one row per ward (never merged), grouped/ordered by the Owner's report
    # layout; wards outside the layout are listed only when admin-mapped, on
    # standby, or carrying a stored edit.
    standby_by_ward: dict[uuid.UUID | None, int] = {}
    for t in open_txs:
        if _no_hn_at(t, cutoff_at):
            key = t.ward_id if t.ward_id in mappings else None
            standby_by_ward[key] = standby_by_ward.get(key, 0) + 1
    extra = [daily_report_service.UNSPECIFIED_LABEL] if None in standby_by_ward else []
    extra += sorted(
        k[len(WARD_KEY_PREFIX):] for k in overrides if k.startswith(WARD_KEY_PREFIX) and k[len(WARD_KEY_PREFIX):]
    )
    ward_rows = daily_report_service.build_ward_rows(mappings, {w for w in standby_by_ward if w}, extra)
    wards = []
    for r in ward_rows:
        override = overrides.get(ward_key(r.label))
        system = sum(standby_by_ward.get(w, 0) for w in r.ward_ids) if r.ward_ids else (
            standby_by_ward.get(None, 0) if r.label == daily_report_service.UNSPECIFIED_LABEL else 0
        )
        wards.append(
            FieldValue(
                key=ward_key(r.label),
                label=r.label,
                system_value=system,
                override_value=override,
                mode=r.mode,
                treatment=r.treatment,
                # LINE text: every admin-mapped ward (even at zero), plus any with standby or an edit.
                text_order=r.sort_order,
                text_label=r.text_label,
                in_text=(r.ward_id is not None and r.listed) or bool(system) or override is not None,
            )
        )

    created_ok = [e for e in equipment if e.created_at is None or e.created_at <= cutoff_at]
    devices = sum(
        1
        for e in created_ok
        if e.status in (EquipmentStatus.AVAILABLE_AT_POOL, EquipmentStatus.ISSUED_TO_WARD)
        and e.id not in open_equipment_ids
    )
    devices_f = FieldValue(KEY_BME_DEVICES, "BME เครื่องใหม่", devices, overrides.get(KEY_BME_DEVICES))

    cfg = await get_config(db, ROLE_INFUSION)
    baseline = Baseline(
        chargers=cfg.chargers if cfg else None,
        clamps=cfg.clamps if cfg else None,
        set_at=cfg.baseline_set_at if cfg else None,
    )
    chargers_sys: int | None = None
    clamps_sys: int | None = None
    if baseline.set_at is not None and baseline.set_at <= cutoff_at:
        dc, dk = await _stock_delta(db, infusion_cats, baseline.set_at, cutoff_at)
        if baseline.chargers is not None:
            chargers_sys = max(0, baseline.chargers + dc)
        if baseline.clamps is not None:
            clamps_sys = max(0, baseline.clamps + dk)
    chargers_f = FieldValue(KEY_CHARGERS, "สายชาร์จ", chargers_sys, overrides.get(KEY_CHARGERS))
    clamps_f = FieldValue(KEY_CLAMPS, "Clamp", clamps_sys, overrides.get(KEY_CLAMPS))
    parts = [devices_f.effective_value, chargers_f.effective_value, clamps_f.effective_value]
    ready_sys = None if any(p is None for p in parts) else min(parts)
    ready_f = FieldValue(KEY_READY, "พร้อมใช้งาน", ready_sys, overrides.get(KEY_READY))

    # ---- pneumatic pump
    p_equipment = await _category_equipment(db, pneumatic_cats)
    p_open = await _open_at_cutoff(db, {e.id for e in p_equipment}, cutoff_at)
    p_ids = {e.id for e in p_equipment}
    returned = 0
    if p_ids:
        rows = (
            await db.execute(
                select(BorrowTransaction.id).where(
                    BorrowTransaction.equipment_id.in_(p_ids),
                    BorrowTransaction.returned_at.is_not(None),
                    BorrowTransaction.returned_at >= day_start,
                    BorrowTransaction.returned_at <= cutoff_at,
                )
            )
        ).all()
        returned = len(rows)

    return StandbySummary(
        summary_date=summary_date,
        cutoff=cutoff,
        cutoff_at=cutoff_at,
        business_day_start=day_start,
        infusion_categories=[c.name for c in infusion_cats],
        pneumatic_categories=[c.name for c in pneumatic_cats],
        wards=wards,
        bme_devices=devices_f,
        chargers=chargers_f,
        clamps=clamps_f,
        ready=ready_f,
        baseline=baseline,
        pneumatic_in_use=FieldValue(
            KEY_PNEUMATIC_IN_USE, "เครื่องที่ใช้งานอยู่", len(p_open), overrides.get(KEY_PNEUMATIC_IN_USE)
        ),
        pneumatic_returned=FieldValue(
            KEY_PNEUMATIC_RETURNED, "รับคืนเครื่องวันนี้", returned, overrides.get(KEY_PNEUMATIC_RETURNED)
        ),
    )


async def standby_by_label(db: AsyncSession, report_date: date) -> dict[str, int]:
    """PR30 Excel "Stand By" column: effective per-row values of the DAY
    cut-off (20:00) of the report date."""
    summary = await build_summary(db, report_date, "day")
    return {w.label: w.effective_value for w in summary.wards if w.effective_value}


# --------------------------------------------------------------------------
# LINE-style copy text
# --------------------------------------------------------------------------


def _num(v: int | None) -> str:
    """Owner decision: every zero (and every blank) shows as "-" in the LINE text."""
    return "-" if not v else str(v)


def render_text(summary: StandbySummary) -> str:
    d = summary.summary_date
    lines = ["Infusion pump standby", f"{d.day:02d}/{d.month:02d}/{d.year}"]
    # LINE text keeps the admin sort_order (stable: layout order breaks ties).
    for w in sorted(summary.wards, key=lambda w: w.text_order):
        v = w.effective_value
        # Same rows as before D18: every admin-mapped ward (zero shows "-"), plus any
        # row with standby or an edit; empty layout placeholder rows stay out.
        if not w.in_text:
            continue
        name = w.text_label or w.label
        lines.append(f"{name} = -" if not v else f"{name} = {v} เครื่อง")
    lines += [
        f"BME = เครื่องใหม่ {_num(summary.bme_devices.effective_value)} เครื่อง",
        f"🟢พร้อมใช้งาน {_num(summary.ready.effective_value)} เครื่อง",
        f"สายชาร์จ = {_num(summary.chargers.effective_value)}  Clamp = {_num(summary.clamps.effective_value)}",
        "🟡 Pneumatic PUMP🟡",
        f"เครื่องที่ใช้งานอยู่ ⏩ : {_num(summary.pneumatic_in_use.effective_value)}",
        f"รับคืนเครื่องวันนี้ ⏩ : {_num(summary.pneumatic_returned.effective_value)}",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Writes (overrides, baseline, category mapping) -- all audited
# --------------------------------------------------------------------------


async def set_override(db: AsyncSession, **kwargs) -> StandbySummaryOverride | None:
    """Race-safe upsert: two concurrent first edits of the same key collide on
    the unique (date, cut-off, field_key) constraint; the loser rolls back and
    retries once, now finding the row and updating it. Never a 500."""
    try:
        return await _set_override_once(db, **kwargs)
    except IntegrityError:
        await db.rollback()
        return await _set_override_once(db, **kwargs)


async def _set_override_once(
    db: AsyncSession,
    *,
    summary_date: date,
    cutoff: str,
    field_key: str,
    value: int | None,
    actor_user_id: uuid.UUID,
    request: Request | None,
) -> StandbySummaryOverride | None:
    """Create/replace the edited value; ``value=None`` removes it (reset)."""
    validate_cutoff(cutoff)
    section = section_for_key(field_key)
    if value is not None and not 0 <= value <= MAX_OVERRIDE_VALUE:
        raise InvalidInputError(f"'value' must be between 0 and {MAX_OVERRIDE_VALUE}")
    row = (
        await db.execute(
            select(StandbySummaryOverride).where(
                StandbySummaryOverride.summary_date == summary_date,
                StandbySummaryOverride.cutoff == cutoff,
                StandbySummaryOverride.field_key == field_key,
            )
        )
    ).scalar_one_or_none()
    ident = {"summary_date": summary_date.isoformat(), "cutoff": cutoff, "field_key": field_key}
    now = datetime.now(timezone.utc)
    if value is None:
        if row is None:
            return None
        before = {**ident, "value": row.value}
        entity_id = row.id
        await db.delete(row)
        await record_audit_event(
            db,
            actor_user_id=actor_user_id,
            action=AUDIT_ACTION_DELETE,
            entity_type=AUDIT_ENTITY_STANDBY_OVERRIDE,
            entity_id=entity_id,
            before=before,
            request=request,
        )
        await db.commit()
        return None
    before = None
    action = AUDIT_ACTION_CREATE
    if row is None:
        row = StandbySummaryOverride(summary_date=summary_date, cutoff=cutoff, section=section, field_key=field_key)
        db.add(row)
    else:
        action = AUDIT_ACTION_UPDATE
        before = {**ident, "value": row.value}
    row.value = value
    row.edited_by_user_id = actor_user_id
    row.edited_at = now
    await db.flush()
    await record_audit_event(
        db,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=AUDIT_ENTITY_STANDBY_OVERRIDE,
        entity_id=row.id,
        before=before,
        after={**ident, "value": value},
        request=request,
    )
    await db.commit()
    return row


async def _ensure_config(db: AsyncSession, role: str) -> tuple[StandbySummaryConfig, bool]:
    if role not in STANDBY_ROLES:
        raise InvalidInputError("'category_role' must be 'infusion' or 'pneumatic'")
    cfg = await get_config(db, role)
    if cfg is not None:
        return cfg, False
    cfg = StandbySummaryConfig(category_role=role)
    db.add(cfg)
    await db.flush()
    return cfg, True


def _config_dict(cfg: StandbySummaryConfig) -> dict:
    return {
        "category_role": cfg.category_role,
        "category_id": str(cfg.category_id) if cfg.category_id else None,
        "chargers": cfg.chargers,
        "clamps": cfg.clamps,
        "baseline_set_at": cfg.baseline_set_at.isoformat() if cfg.baseline_set_at else None,
    }


async def set_baseline(
    db: AsyncSession,
    *,
    category_role: str,
    chargers: int,
    clamps: int,
    actor_user_id: uuid.UUID,
    request: Request | None,
) -> StandbySummaryConfig:
    """Stock at the pool NOW; later dispatch/receipt checks move it from here."""
    cfg, created = await _ensure_config(db, category_role)
    before = None if created else _config_dict(cfg)
    cfg.chargers = chargers
    cfg.clamps = clamps
    cfg.baseline_set_at = datetime.now(timezone.utc)
    cfg.baseline_set_by_user_id = actor_user_id
    await db.flush()
    await record_audit_event(
        db,
        actor_user_id=actor_user_id,
        action=AUDIT_ACTION_CREATE if created else AUDIT_ACTION_UPDATE,
        entity_type=AUDIT_ENTITY_STANDBY_CONFIG,
        entity_id=cfg.id,
        before=before,
        after=_config_dict(cfg),
        request=request,
    )
    await db.commit()
    return cfg


async def set_category(
    db: AsyncSession,
    *,
    category_role: str,
    category_id: uuid.UUID | None,
    actor_user_id: uuid.UUID,
    request: Request | None,
) -> StandbySummaryConfig:
    if category_id is not None and await db.get(EquipmentCategory, category_id) is None:
        raise ResourceNotFoundError("Category not found")
    cfg, created = await _ensure_config(db, category_role)
    before = None if created else _config_dict(cfg)
    cfg.category_id = category_id
    await db.flush()
    await record_audit_event(
        db,
        actor_user_id=actor_user_id,
        action=AUDIT_ACTION_CREATE if created else AUDIT_ACTION_UPDATE,
        entity_type=AUDIT_ENTITY_STANDBY_CONFIG,
        entity_id=cfg.id,
        before=before,
        after=_config_dict(cfg),
        request=request,
    )
    await db.commit()
    return cfg
