"""Roadmap PR25E slice B4b -- per-equipment timeline, human-confirmed
"Apply sequence" and collision statistics
(docs/design/PR25D_OFFLINE_OPERATION_PLAN.md sections 9.7, 16.1; Owner
decisions D7 and D8).

* **Timeline** -- read only: committed transactions for one equipment (last
  7 days, plus any still-open one) merged with the reviewable ledger ops for
  it, ordered by corrected event time; within one device ``device_seq``
  overrides time. Events whose uncertainty bands overlap are flagged.
* **Apply sequence** -- the resolver confirms an ordered list of reviewable
  ops for one equipment. Each op is run through
  ``sync_review_service.apply_now`` (hence the normal borrow/return
  services) as its OWN transaction, in the given order, stopping at the
  first failure (design 9.7 point 4: the services own their commit
  boundaries; a prefix is a set of true, individually valid events). Not
  all-or-nothing, by design. Idempotency comes from apply_now's conditional
  UPDATE on the ledger status.
* **Stats / CSV** -- read only aggregates feeding the post-pilot decision on
  auto-sequencing (D8). NOTHING here applies anything automatically; no code
  for ``SYNC_AUTO_SEQUENCE`` exists.
"""
import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DomainError, InvalidInputError, ResourceNotFoundError
from app.crud import transaction as transaction_crud
from app.models.client_operation import (
    OP_STATUS_CONFLICT,
    OP_STATUS_RESOLVED,
    OP_TYPE_DISPATCH,
    ClientOperation,
)
from app.models.equipment import Equipment, EquipmentStatus
from app.models.master_data import Ward
from app.models.transaction import BorrowTransaction, TransactionStatus
from app.models.user import User
from app.services import sync_review_service as review

TIMELINE_WINDOW = timedelta(days=7)
MAX_SCAN_ROWS = 2000
MAX_STATS_ROWS = 50_000
BASE_BAND_S = 30
MAX_STATS_RANGE_DAYS = 366

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _utc(v: datetime) -> datetime:
    return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)


def _band_s(row: ClientOperation) -> int:
    """± (30 s + 1 min per hour since the device clock offset was measured)."""
    return BASE_BAND_S + int((row.offset_age_s or 0) / 60)


# ---- equipment resolution -------------------------------------------------

async def _equipment_ids(db: AsyncSession, rows: list[ClientOperation]) -> dict[uuid.UUID, uuid.UUID | None]:
    """op_id -> equipment id. A receipt whose target transaction does not
    exist yet is resolved through a (reviewable) dispatch with that op_id."""
    out: dict[uuid.UUID, uuid.UUID | None] = {}
    receipts: dict[uuid.UUID, uuid.UUID] = {}
    for r in rows:
        body = review._body(r)
        if r.op_type == OP_TYPE_DISPATCH:
            out[r.op_id] = review._uuid_or_none(body.get("equipment_id"))
        elif (t := review._uuid_or_none(body.get("transaction_id"))):
            receipts[r.op_id] = t
        else:
            out[r.op_id] = None
    if receipts:
        tx_ids = set(receipts.values())
        tx_eq = {
            t.id: t.equipment_id
            for t in (await db.execute(select(BorrowTransaction).where(BorrowTransaction.id.in_(tx_ids)))).scalars()
        }
        missing = tx_ids - set(tx_eq)
        disp_eq: dict[uuid.UUID, uuid.UUID | None] = {}
        if missing:
            for d in (
                await db.execute(
                    select(ClientOperation).where(
                        ClientOperation.op_id.in_(missing), ClientOperation.op_type == OP_TYPE_DISPATCH
                    )
                )
            ).scalars():
                disp_eq[d.op_id] = review._uuid_or_none(review._body(d).get("equipment_id"))
        for op_id, t in receipts.items():
            out[op_id] = tx_eq.get(t) or disp_eq.get(t)
    return out


# ---- timeline ---------------------------------------------------------------

async def _reviewable_for_equipment(
    db: AsyncSession, equipment_id: uuid.UUID, is_admin: bool
) -> tuple[list[ClientOperation], bool]:
    """Newest-first scan of the reviewable set (the equipment lives inside the
    JSON payload / target transaction, so it is matched after loading); a
    ``truncated`` flag says the scan hit its cap."""
    now = review._now()
    rows = list(
        (
            await db.execute(
                select(ClientOperation)
                .where(review._visible_clause(now, "unresolved", is_admin))
                .order_by(ClientOperation.received_at.desc(), ClientOperation.op_id)
                .limit(MAX_SCAN_ROWS + 1)
            )
        )
        .scalars()
        .all()
    )
    truncated = len(rows) > MAX_SCAN_ROWS
    rows = rows[:MAX_SCAN_ROWS]
    eq_of = await _equipment_ids(db, rows)
    return [r for r in rows if eq_of.get(r.op_id) == equipment_id], truncated


def _op_time(row: ClientOperation) -> datetime:
    return _utc(row.occurred_at or row.received_at)


def _corrected_order(rows: list[ClientOperation]) -> list[ClientOperation]:
    """Corrected-time order; within one device ``device_seq`` overrides time:
    the slots a device occupies are refilled with its ops in seq order."""
    ordered = sorted(rows, key=lambda r: (_op_time(r), str(r.op_id)))
    by_device: dict[uuid.UUID, list[ClientOperation]] = {}
    for r in ordered:
        by_device.setdefault(r.device_id, []).append(r)
    queues = {d: iter(sorted(v, key=lambda r: r.device_seq)) for d, v in by_device.items()}
    return [next(queues[r.device_id]) for r in ordered]


async def timeline(db: AsyncSession, equipment_id: uuid.UUID, *, is_admin: bool) -> dict:
    eq = await db.get(Equipment, equipment_id)
    if eq is None or getattr(eq, "deleted_at", None) is not None:
        raise ResourceNotFoundError("Equipment not found")
    now = review._now()
    cutoff = now - TIMELINE_WINDOW
    rows, truncated = await _reviewable_for_equipment(db, equipment_id, is_admin)
    txs = (
        (
            await db.execute(
                select(BorrowTransaction).where(
                    BorrowTransaction.equipment_id == equipment_id,
                    (BorrowTransaction.borrowed_at >= cutoff)
                    | (BorrowTransaction.returned_at >= cutoff)
                    | (BorrowTransaction.status == TransactionStatus.OPEN),
                )
            )
        )
        .scalars()
        .all()
    )
    ctx = await review._enrich(db, rows)
    user_ids = {u for t in txs for u in (t.borrower_user_id, t.received_by_user_id) if u}
    ward_ids = {t.ward_id for t in txs if t.ward_id}
    users = dict(ctx["users"])
    wards = dict(ctx["wards"])
    if user_ids - set(users):
        users.update({u.id: u for u in (await db.execute(select(User).where(User.id.in_(user_ids - set(users))))).scalars()})
    if ward_ids - set(wards):
        wards.update({w.id: w for w in (await db.execute(select(Ward).where(Ward.id.in_(ward_ids - set(wards))))).scalars()})

    events: list[dict] = []
    for t in txs:
        ward = wards.get(t.ward_id) if t.ward_id else None
        base = {"source": "transaction", "band_s": 0, "selectable": False, "transaction_id": t.id,
                "ward_name": ward.name if ward else None}
        borrowed = _utc(t.borrowed_at)
        if borrowed >= cutoff or t.status == TransactionStatus.OPEN:
            events.append({**base, "kind": "dispatch", "at": borrowed,
                           "operator": review._user_ref(users, t.borrower_user_id)})
        if t.returned_at is not None and _utc(t.returned_at) >= cutoff:
            events.append({**base, "kind": "receipt", "at": _utc(t.returned_at),
                           "operator": review._user_ref(users, t.received_by_user_id),
                           "receipt_outcome": t.condition_on_return})
    for r in _corrected_order(rows):
        item = review._item(r, ctx)
        events.append({
            "source": "op", "kind": r.op_type, "at": _op_time(r), "band_s": _band_s(r), "selectable": True,
            "op_id": r.op_id, "status": r.status, "result_code": r.result_code, "admin_only": item["admin_only"],
            "stale_context": item["stale_context"], "time_flag": r.time_flag, "device_id": r.device_id,
            "device_seq": r.device_seq, "operator": item["operator"], "ward_name": item["ward_name"],
            "receipt_outcome": item["receipt_outcome"], "transaction_id": item["transaction_id"],
        })
    # Committed history first on equal time; ops keep their corrected order
    # (sort is stable, and `rows` were emitted in corrected order).
    events.sort(key=lambda e: (e["at"], 0 if e["source"] == "transaction" else 1))
    # device_seq override survives the final time sort only if re-applied.
    events = _reapply_device_seq(events)
    for i, e in enumerate(events):
        # Bands of events from different sources/devices overlap => the
        # relative order cannot be trusted. Same-device order is by seq.
        e["order_uncertain"] = any(
            j != i
            and (o["source"] != e["source"] or o.get("device_id") != e.get("device_id"))
            and abs((o["at"] - e["at"]).total_seconds()) <= o["band_s"] + e["band_s"]
            for j, o in enumerate(events)
        )
    return {
        "equipment": {"id": eq.id, "bcm_code": eq.bcm_code, "equipment_name": eq.equipment_name, "status": eq.status.value},
        "server_time": now,
        "truncated": truncated,
        "events": events,
    }


def _reapply_device_seq(events: list[dict]) -> list[dict]:
    slots: dict[uuid.UUID, list[int]] = {}
    for i, e in enumerate(events):
        if e["source"] == "op":
            slots.setdefault(e["device_id"], []).append(i)
    out = list(events)
    for idxs in slots.values():
        for i, e in zip(idxs, sorted((events[i] for i in idxs), key=lambda e: e["device_seq"])):
            out[i] = e
    return out


# ---- apply sequence -------------------------------------------------------

def _step(op_id, ok, code=None, message=None, **extra) -> dict:
    return {"op_id": op_id, "ok": ok, "code": code, "message": message, **extra}


async def _simulate(db: AsyncSession, eq: Equipment, rows: list[ClientOperation]) -> tuple[list[dict], dict | None, list]:
    open_tx = await transaction_crud.get_open_transaction_for_equipment(db, eq.id)
    open_id = open_tx.id if open_tx else None
    available = eq.status == EquipmentStatus.AVAILABLE_AT_POOL
    steps: list[dict] = []
    for n, r in enumerate(rows):
        body = review._body(r)
        code = None
        if r.op_type == OP_TYPE_DISPATCH:
            if not available:
                code = "EQUIPMENT_NOT_AVAILABLE"
            else:
                open_id, available = r.op_id, False
        else:
            tx_id = review._uuid_or_none(body.get("transaction_id"))
            if tx_id is not None and tx_id == open_id:
                open_id, available = None, body.get("receipt_outcome") == "usable"
            else:
                tx = await transaction_crud.get_by_id(db, tx_id) if tx_id else None
                code = "TRANSACTION_ALREADY_RETURNED" if tx is not None else "TRANSACTION_NOT_FOUND"
        if code:
            failed = _step(r.op_id, False, code, "Would not hold at this position in the sequence.")
            return steps, failed, [x.op_id for x in rows[n + 1 :]]
        steps.append(_step(r.op_id, True))
    return steps, None, []


async def apply_sequence(
    db: AsyncSession,
    equipment_id: uuid.UUID,
    op_ids: list[uuid.UUID],
    resolver_id: uuid.UUID,
    *,
    is_admin: bool,
    dry_run: bool = False,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    if len(set(op_ids)) != len(op_ids):
        raise InvalidInputError("op_ids must not repeat.")
    eq = await db.get(Equipment, equipment_id)
    if eq is None or getattr(eq, "deleted_at", None) is not None:
        raise ResourceNotFoundError("Equipment not found")
    # Whole-request validation BEFORE any write: unknown (404), not open /
    # already resolved (409), administrator-only class (403).
    rows = [await review._load_visible(db, oid, is_admin, include_resolved=False) for oid in op_ids]
    eq_of = await _equipment_ids(db, rows)
    if any(eq_of.get(r.op_id) != equipment_id for r in rows):
        raise InvalidInputError("All operations must belong to the equipment of the timeline.")
    last_seq: dict[uuid.UUID, int] = {}
    for r in rows:
        if r.device_seq < last_seq.get(r.device_id, -1):
            raise InvalidInputError("Operations from one device must be listed in device_seq order.")
        last_seq[r.device_id] = r.device_seq
    if dry_run:
        steps, failed, remaining = await _simulate(db, eq, rows)
        return {"dry_run": True, "steps": steps, "failed": failed, "remaining": remaining}

    steps: list[dict] = []
    for n, oid in enumerate(op_ids):
        try:
            res = await review.apply_now(db, oid, resolver_id, is_admin=is_admin, ip_address=ip_address, user_agent=user_agent)
        except DomainError as exc:
            if not steps:
                raise  # nothing applied: same 4xx contract as apply-now
            return {
                "dry_run": False,
                "steps": steps,
                "failed": _step(oid, False, exc.code, exc.message),
                "remaining": op_ids[n + 1 :],
            }
        except Exception:  # unexpected: report the committed prefix, never lose it
            if not steps:
                raise
            await db.rollback()
            return {
                "dry_run": False,
                "steps": steps,
                "failed": _step(oid, False, "INTERNAL_ERROR", "Unexpected error; the run stopped."),
                "remaining": op_ids[n + 1 :],
            }
        steps.append(_step(oid, True, new_op_id=res["new_op_id"], transaction_id=res["transaction_id"]))
    return {"dry_run": False, "steps": steps, "failed": None, "remaining": []}


# ---- statistics / CSV -----------------------------------------------------

def _range(range_from: datetime | None, range_to: datetime | None) -> tuple[datetime, datetime]:
    end = _utc(range_to) if range_to else review._now()
    start = _utc(range_from) if range_from else end - timedelta(days=30)
    if start >= end:
        raise InvalidInputError("'from' must be earlier than 'to'.")
    if end - start > timedelta(days=MAX_STATS_RANGE_DAYS):
        raise InvalidInputError(f"Range may not exceed {MAX_STATS_RANGE_DAYS} days.")
    return start, end


async def _conflict_rows(db: AsyncSession, start: datetime, end: datetime) -> tuple[list[ClientOperation], bool]:
    """Ops that conflicted (still open or since resolved) received in range."""
    rows = list(
        (
            await db.execute(
                select(ClientOperation)
                .where(
                    ClientOperation.status.in_((OP_STATUS_CONFLICT, OP_STATUS_RESOLVED)),
                    ClientOperation.received_at >= start,
                    ClientOperation.received_at <= end,
                )
                .order_by(ClientOperation.received_at, ClientOperation.op_id)
                .limit(MAX_STATS_ROWS + 1)
            )
        ).scalars()
    )
    truncated = len(rows) > MAX_STATS_ROWS
    return rows[:MAX_STATS_ROWS], truncated


def _classify_group(group: list[ClientOperation]) -> tuple[str, bool]:
    """(outcome, auto_eligible) for the ops of one equipment.

    outcome: open | same | different | dismissed_only | mixed. ``same`` = every
    op was applied, in the corrected-time order. auto_eligible = the
    conditions a future auto-sequencer would need (cross-device, no
    stale_context, no overlapping bands); evaluated for evidence only."""
    ordered = _corrected_order(group)
    if any(r.status == OP_STATUS_CONFLICT for r in group):
        outcome = "open"
    else:
        applied = [r for r in group if r.resolution == "applied_as"]
        if not applied:
            outcome = "dismissed_only"
        elif len(applied) < len(group):
            outcome = "mixed"
        else:
            by_resolved = sorted(group, key=lambda r: (_utc(r.resolved_at), str(r.op_id)))
            outcome = "same" if [r.op_id for r in by_resolved] == [r.op_id for r in ordered] else "different"
    overlap = any(
        abs((_op_time(a) - _op_time(b)).total_seconds()) <= _band_s(a) + _band_s(b)
        for i, a in enumerate(ordered)
        for b in ordered[i + 1 :]
    )
    eligible = len({r.device_id for r in group}) >= 2 and not any(r.stale_context for r in group) and not overlap
    return outcome, eligible


async def stats(db: AsyncSession, range_from: datetime | None, range_to: datetime | None) -> dict:
    start, end = _range(range_from, range_to)
    rows, truncated = await _conflict_rows(db, start, end)
    by_code: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_day: dict[str, int] = {}
    for r in rows:
        by_code[r.result_code or "NONE"] = by_code.get(r.result_code or "NONE", 0) + 1
        by_status[r.status] = by_status.get(r.status, 0) + 1
        day = _utc(r.received_at).date().isoformat()
        by_day[day] = by_day.get(day, 0) + 1
    eq_of = await _equipment_ids(db, rows)
    grouped: dict[uuid.UUID, list[ClientOperation]] = {}
    for r in rows:
        if (e := eq_of.get(r.op_id)):
            grouped.setdefault(e, []).append(r)
    outcomes = {"open": 0, "same": 0, "different": 0, "dismissed_only": 0, "mixed": 0}
    groups = cross = eligible_n = eligible_same = eligible_diff = 0
    for g in grouped.values():
        if len(g) < 2:
            continue
        groups += 1
        outcome, eligible = _classify_group(g)
        outcomes[outcome] += 1
        cross += len({r.device_id for r in g}) >= 2
        if eligible:
            eligible_n += 1
            eligible_same += outcome == "same"
            eligible_diff += outcome == "different"
    decided = outcomes["same"] + outcomes["different"]
    return {
        "range_from": start,
        "range_to": end,
        "total_conflicts": len(rows),
        "by_result_code": dict(sorted(by_code.items())),
        "by_status": dict(sorted(by_status.items())),
        "by_day": dict(sorted(by_day.items())),
        "truncated": truncated,
        "groups": {
            "equipment_with_multiple_conflicts": groups,
            "cross_device": cross,
            "by_outcome": outcomes,
            "agreement_rate": round(outcomes["same"] / decided, 4) if decided else None,
            "would_have_auto_sequenced": {
                "conditions_met": eligible_n,
                "resolved_same_order": eligible_same,
                "resolved_differently": eligible_diff,
                "agreement_rate": round(eligible_same / (eligible_same + eligible_diff), 4)
                if (eligible_same + eligible_diff)
                else None,
            },
        },
    }


def _cell(v) -> str:
    s = "" if v is None else (v.isoformat() if isinstance(v, datetime) else str(v))
    return "'" + s if s.lstrip(" \t\r\n").startswith(_FORMULA_PREFIXES) or s.startswith(_FORMULA_PREFIXES) else s


CSV_COLUMNS = (
    "op_id", "op_type", "status", "result_code", "resolution", "bcm_code", "ward", "operator",
    "resolved_by", "occurred_at", "received_at", "resolved_at", "device_id", "stale_context", "time_flag",
)


async def export_csv(db: AsyncSession, range_from: datetime | None, range_to: datetime | None) -> str:
    """No payload bodies, no notes, no patient data (none exists): BCM code,
    ward, operator, times and codes only."""
    start, end = _range(range_from, range_to)
    rows, _ = await _conflict_rows(db, start, end)
    ctx = await review._enrich(db, rows)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for r in rows:
        it = review._item(r, ctx)
        w.writerow([
            _cell(v) for v in (
                r.op_id, r.op_type, r.status, r.result_code, r.resolution,
                (it["equipment"] or {}).get("bcm_code"), it["ward_name"],
                (it["operator"] or {}).get("full_name"), (it["resolved_by"] or {}).get("full_name"),
                r.occurred_at, r.received_at, r.resolved_at, r.device_id, r.stale_context, r.time_flag,
            )
        ])
    return buf.getvalue()
