"""Roadmap PR25E slice B3 -- restore-recovery verify, sync status and
volume/clock-skew statistics (docs/design/PR25D_OFFLINE_OPERATION_PLAN.md
sections 10, 16, 16.1).

Read-only over ``client_operations`` except for one counts-only audit row per
verify call that found unknown ids (the section 16 restore signal). Nothing
here touches equipment or transaction state, and no payload body is ever
selected or returned.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import audit as audit_crud
from app.models.audit import AuditLog
from app.models.client_operation import (
    ALL_OP_STATUSES,
    OP_STATUS_CONFLICT,
    ClientOperation,
)

JOURNAL_WINDOW_HOURS = 48
AUDIT_ACTION_VERIFY = "sync_verify"
AUDIT_ENTITY_SYNC = "sync"
OFFLINE_LAG_S = 120  # "recorded offline": received more than 2 min after occurred_at
MAX_STATS_RANGE_DAYS = 366
MAX_STATS_ROWS = 200_000
_CHUNK = 500

OFFSET_BUCKETS_MS = (1_000, 5_000, 30_000, 5 * 60_000, 60 * 60_000)
OFFSET_AGE_BUCKETS_S = (60, 600, 3600, 6 * 3600, 24 * 3600)
LAG_BUCKETS_S = (120, 600, 3600, 6 * 3600, 24 * 3600, 48 * 3600)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


async def verify(
    db: AsyncSession, user_id: uuid.UUID, op_ids: list[uuid.UUID], *, ip_address: str | None = None, user_agent: str | None = None
) -> list[uuid.UUID]:
    """Return the requested ids (request order, de-duplicated) for which the
    caller has no ledger row. Only the caller's own operations count as known
    (original operator or submitter), so an id that belongs to someone else is
    indistinguishable from one the server never saw."""
    ordered = list(dict.fromkeys(op_ids))
    known: set[uuid.UUID] = set()
    for i in range(0, len(ordered), _CHUNK):
        chunk = ordered[i : i + _CHUNK]
        rows = await db.execute(
            select(ClientOperation.op_id).where(
                ClientOperation.op_id.in_(chunk),
                or_(ClientOperation.user_id == user_id, ClientOperation.submitted_by_user_id == user_id),
            )
        )
        known.update(rows.scalars().all())
    unknown = [i for i in ordered if i not in known]
    # Counts only (never the ids): feeds the status "restore happened" signal.
    await audit_crud.create(
        db,
        user_id=user_id,
        action=AUDIT_ACTION_VERIFY,
        entity_type=AUDIT_ENTITY_SYNC,
        entity_id=None,
        after_data={"checked": len(ordered), "unknown": len(unknown)},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    return unknown


async def status(db: AsyncSession, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=JOURNAL_WINDOW_HOURS)
    by_status = {s: 0 for s in ALL_OP_STATUSES}
    rows = await db.execute(
        select(ClientOperation.status, func.count()).where(ClientOperation.received_at >= since).group_by(ClientOperation.status)
    )
    for s, n in rows.all():
        by_status[s] = n
    resent = (
        await db.execute(
            select(func.coalesce(func.sum(ClientOperation.attempt_count - 1), 0)).where(ClientOperation.received_at >= since)
        )
    ).scalar_one()
    flagged = (
        await db.execute(
            select(func.count()).where(ClientOperation.received_at >= since, ClientOperation.time_flag.is_not(None))
        )
    ).scalar_one()
    unresolved, oldest = (
        await db.execute(
            select(func.count(), func.min(ClientOperation.received_at)).where(ClientOperation.status == OP_STATUS_CONFLICT)
        )
    ).one()
    oldest = _utc(oldest)
    verify_total = (
        await db.execute(
            select(func.count()).where(AuditLog.action == AUDIT_ACTION_VERIFY, AuditLog.created_at >= since)
        )
    ).scalar_one()
    verify_logs = await db.execute(
        select(AuditLog.after_data).where(AuditLog.action == AUDIT_ACTION_VERIFY, AuditLog.created_at >= since)
    )
    with_unknown = sum(1 for (d,) in verify_logs.all() if d and d.get("unknown", 0) > 0)
    return {
        "window_hours": JOURNAL_WINDOW_HOURS,
        "server_time": now,
        "ops_by_status": by_status,
        "resent_attempts": int(resent or 0),
        "time_flag_ops": flagged,
        "unresolved_conflicts": unresolved,
        "oldest_unresolved_conflict_age_s": int((now - oldest).total_seconds()) if oldest else None,
        "verify_calls": verify_total,
        "verify_calls_with_unknown": with_unknown,
    }


def _histogram(values: list[float], bounds: tuple[int, ...]) -> dict[str, int]:
    labels = [f"<={b}" for b in bounds] + [f">{bounds[-1]}"]
    out = {label: 0 for label in labels}
    for v in values:
        for b, label in zip(bounds, labels):
            if v <= b:
                out[label] += 1
                break
        else:
            out[labels[-1]] += 1
    return out


def _percentile(sorted_values: list[float], q: float) -> float | None:
    if not sorted_values:
        return None
    idx = max(0, min(len(sorted_values) - 1, int(round(q * (len(sorted_values) - 1)))))
    return sorted_values[idx]


async def stats(db: AsyncSession, range_from: datetime, range_to: datetime) -> dict:
    """Section 16.1 volume and clock-skew statistics for ops received in
    ``[range_from, range_to)``. Selects scalar columns only (never ``payload``)
    and returns counts and histograms only. Collision statistics are B4b."""
    rows = (
        await db.execute(
            select(
                ClientOperation.status,
                ClientOperation.received_at,
                ClientOperation.occurred_at,
                ClientOperation.clock_offset_ms,
                ClientOperation.offset_age_s,
                ClientOperation.time_flag,
                ClientOperation.resolved_at,
            )
            .where(ClientOperation.received_at >= range_from, ClientOperation.received_at < range_to)
            .order_by(ClientOperation.received_at)
            .limit(MAX_STATS_ROWS + 1)
        )
    ).all()
    truncated = len(rows) > MAX_STATS_ROWS
    rows = rows[:MAX_STATS_ROWS]

    total = len(rows)
    by_status = {s: 0 for s in ALL_OP_STATUSES}
    lags: list[float] = []
    offsets: list[float] = []
    offset_ages: list[float] = []
    flags: dict[str, int] = {}
    resolution_s: list[float] = []
    for status_, received, occurred, offset_ms, offset_age, flag, resolved_at in rows:
        by_status[status_] += 1
        received, occurred, resolved_at = _utc(received), _utc(occurred), _utc(resolved_at)
        if received and occurred:
            lags.append(max(0.0, (received - occurred).total_seconds()))
        if offset_ms is not None:
            offsets.append(abs(offset_ms))
        if offset_age is not None:
            offset_ages.append(offset_age)
        if flag:
            flags[flag] = flags.get(flag, 0) + 1
        if resolved_at and received:
            resolution_s.append(max(0.0, (resolved_at - received).total_seconds()))
    resolution_s.sort()
    offline = sum(1 for v in lags if v > OFFLINE_LAG_S)
    conflicts = by_status["conflict"] + by_status["resolved"]
    flagged = sum(flags.values())
    return {
        "volume": {
            "total_ops": total,
            "truncated": truncated,
            "by_status": by_status,
            "recorded_offline": offline,
            "offline_lag_threshold_s": OFFLINE_LAG_S,
            "conflicts": conflicts,
            "conflicts_per_1000_ops": round(conflicts * 1000 / total, 2) if total else None,
            "resolution_time_s": {
                "count": len(resolution_s),
                "median": _percentile(resolution_s, 0.5),
                "p90": _percentile(resolution_s, 0.9),
            },
        },
        "clock_skew": {
            "abs_clock_offset_ms_histogram": _histogram(offsets, OFFSET_BUCKETS_MS),
            "offset_age_s_histogram": _histogram(offset_ages, OFFSET_AGE_BUCKETS_S),
            "lag_s_histogram": _histogram(lags, LAG_BUCKETS_S),
            "time_flag_ops": flagged,
            "time_flag_share": round(flagged / total, 4) if total else None,
            "time_flag_counts": flags,
        },
    }
