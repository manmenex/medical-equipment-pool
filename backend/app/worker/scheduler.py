import logging
from datetime import date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.equipment import Equipment
from app.models.notification import Notification
from app.models.user import ROLE_ADMIN, ROLE_BIOMEDICAL_ENGINEER, Role, User

logger = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None


async def _notify_engineers(db, title: str, body: str, notif_type: str) -> None:
    result = await db.execute(
        select(User.id).join(Role, Role.id == User.role_id).where(
            Role.name.in_([ROLE_ADMIN, ROLE_BIOMEDICAL_ENGINEER]), User.is_active.is_(True)
        )
    )
    for (user_id,) in result.all():
        db.add(Notification(user_id=user_id, type=notif_type, title=title, body=body))


async def check_pm_cal_due() -> None:
    async with AsyncSessionLocal() as db:
        today = date.today()
        pm_horizon = today + timedelta(days=settings.PM_DUE_SOON_DAYS)
        cal_horizon = today + timedelta(days=settings.CAL_DUE_SOON_DAYS)

        pm_due = (
            await db.execute(
                select(Equipment).where(
                    Equipment.deleted_at.is_(None),
                    Equipment.pm_due_date.is_not(None),
                    Equipment.pm_due_date <= pm_horizon,
                    Equipment.pm_due_date >= today,
                )
            )
        ).scalars().all()
        for eq in pm_due:
            await _notify_engineers(
                db,
                title=f"PM ใกล้ครบกำหนด: {eq.equipment_name}",
                body=f"เครื่อง {eq.asset_number} มีกำหนด PM วันที่ {eq.pm_due_date}",
                notif_type="pm",
            )

        cal_due = (
            await db.execute(
                select(Equipment).where(
                    Equipment.deleted_at.is_(None),
                    Equipment.cal_due_date.is_not(None),
                    Equipment.cal_due_date <= cal_horizon,
                    Equipment.cal_due_date >= today,
                )
            )
        ).scalars().all()
        for eq in cal_due:
            await _notify_engineers(
                db,
                title=f"Calibration ใกล้ครบกำหนด: {eq.equipment_name}",
                body=f"เครื่อง {eq.asset_number} มีกำหนด Calibration วันที่ {eq.cal_due_date}",
                notif_type="calibration",
            )

        await db.commit()
        logger.info("PM/CAL due check complete: %d PM, %d CAL", len(pm_due), len(cal_due))


# The overdue-returns notification job (formerly `check_overdue_returns`,
# registered hourly as "overdue_check") is disabled and removed, not merely
# unregistered. The approved MVP business model
# (`knowledge/adr/ADR-005-transaction-model.md`; `docs/BUSINESS_RULES.md`
# "Dispatch/Return owns transaction lifecycle") has no due-date or overdue
# *workflow* at all -- a transaction is only ever OPEN or CLOSED, and
# "overdue" is not tracked in any form, notification included. The removed
# job re-selected every OPEN transaction past its `due_at` on every hourly
# tick with no de-duplication, so it created a fresh notification for the
# same transaction every hour indefinitely (Codex REQUEST_CHANGES,
# PR7a review round 1, BLOCKER). The fix is to stop running this workflow,
# not to bolt deduplication onto a deprecated feature -- see
# `test_scheduler_never_registers_or_runs_a_disabled_overdue_job` in
# `tests/test_borrow.py` for the regression coverage.


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(check_pm_cal_due, "cron", hour=6, minute=0, id="pm_cal_due_check")
    _scheduler.start()
    logger.info("Scheduler started")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
