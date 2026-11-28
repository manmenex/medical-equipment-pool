"""Admin system-health banner (in-app only; nothing is sent anywhere).

Only checks that can be computed reliably from inside the app container:
legacy sheet sync staleness, the sync review queue, and the D29 HN listener
startup result. The backup age is NOT checked: the backup runs on the host and
its manifests are not mounted into the app container.
"""
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import export_hn
from app.crud.client_operation import reviewable_clause
from app.models.client_operation import ClientOperation
from app.services import sync_service
from app.models.system_heartbeat import (
    HEARTBEAT_LEGACY_SHEET_SYNC,
    HEARTBEAT_RESTORE_DRILL_FAIL,
    HEARTBEAT_RESTORE_DRILL_PASS,
    SystemHeartbeat,
)

SYNC_STALE_AFTER = timedelta(minutes=15)
RESTORE_DRILL_STALE_AFTER = timedelta(days=40)
_TRUE = {"1", "true", "yes", "on"}


async def record_heartbeat(db: AsyncSession, key: str, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    row = await db.get(SystemHeartbeat, key)
    if row is None:
        db.add(SystemHeartbeat(key=key, beat_at=now))
    else:
        row.beat_at = now
    await db.commit()


async def record_restore_drill(db: AsyncSession, status: str, now: datetime | None = None) -> None:
    """pass: clear the failure alert and stamp the last pass. fail: raise the alert."""
    now = now or datetime.now(timezone.utc)
    if status == "pass":
        failed = await db.get(SystemHeartbeat, HEARTBEAT_RESTORE_DRILL_FAIL)
        if failed is not None:
            await db.delete(failed)
        await record_heartbeat(db, HEARTBEAT_RESTORE_DRILL_PASS, now)
    elif status == "fail":
        await record_heartbeat(db, HEARTBEAT_RESTORE_DRILL_FAIL, now)
    else:
        raise ValueError(f"unknown status {status!r}")


def _alert(code: str, severity: str, message_th: str, since: datetime | None) -> dict:
    return {"code": code, "severity": severity, "message_th": message_th, "since": since}


async def compute_alerts(db: AsyncSession, now: datetime | None = None, env=None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    env = os.environ if env is None else env
    alerts: list[dict] = []

    # a. legacy sheet sync stale (only while it is enabled)
    if str(env.get("LEGACY_SHEET_SYNC_ENABLED", "")).strip().lower() in _TRUE:
        row = await db.get(SystemHeartbeat, HEARTBEAT_LEGACY_SHEET_SYNC)
        if row is None:
            alerts.append(_alert("sync_stale", "warning", "ซิงก์ชีตเดิมยังไม่เคยรันสำเร็จ", None))
        elif now - row.beat_at > SYNC_STALE_AFTER:
            mins = int((now - row.beat_at).total_seconds() // 60)
            alerts.append(_alert("sync_stale", "warning", f"ซิงก์ชีตเดิมหยุดทำงานแล้ว {mins} นาที", row.beat_at))

    # c. sync review queue (conflict, or pending past its 48 h window; resolved/dismissed excluded)
    count, oldest = (await db.execute(
        select(func.count(), func.min(ClientOperation.first_seen_at)).where(
            reviewable_clause(now - sync_service.DEPENDENCY_WINDOW)
        )
    )).one()
    if count:
        alerts.append(_alert("sync_review_queue", "warning", f"มีรายการซิงก์รอตรวจสอบ {count} รายการ", oldest))

    # d. D29 HN export listener refused at startup
    startup = export_hn.last_startup_result()
    if startup is not None and not startup[0].enabled and str(env.get("EXPORT_HN_PORT", "")).strip():
        alerts.append(_alert(
            "hn_listener_disabled", "error",
            "ช่องทางส่งออก HN ถูกปิดเพราะตั้งค่าไม่ถูกต้อง", startup[1],
        ))

    # e. monthly restore drill failed 5 times this month (row raised by the host script)
    failed = await db.get(SystemHeartbeat, HEARTBEAT_RESTORE_DRILL_FAIL)
    if failed is not None:
        alerts.append(_alert(
            "restore_drill_failed", "high",
            "ระบบทดสอบกู้คืนรายเดือนมีปัญหา: ไม่ผ่าน 5 ครั้งในเดือนนี้ ตรวจไฟล์ logs\\restore-drill",
            failed.beat_at,
        ))
    # f. last PASS older than 40 days (only once a PASS has ever been recorded)
    passed = await db.get(SystemHeartbeat, HEARTBEAT_RESTORE_DRILL_PASS)
    if passed is not None and failed is None and now - passed.beat_at > RESTORE_DRILL_STALE_AFTER:
        days = (now - passed.beat_at).days
        alerts.append(_alert(
            "restore_drill_stale", "high",
            f"ไม่มีผลทดสอบกู้คืนที่ผ่านมา {days} วันแล้ว ตรวจไฟล์ logs\\restore-drill", passed.beat_at,
        ))
    return alerts
