import logging
import time
import uuid
from datetime import date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.core.config import settings
from app.core.log_context import job_run_id_var
from app.db.session import AsyncSessionLocal
from app.models.equipment import Equipment
from app.models.notification import Notification
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, Role, User

logger = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None


async def _get_recipient_ids(db) -> list:
    # Roadmap PR10: this PM/CAL due-date notification recipient list is
    # unrelated to PR10's own scope, but biomedical_engineer (one of its two
    # pre-PR10 recipient roles) is retired by the role-consolidation
    # migration and can no longer be referenced. Updated to the two
    # confirmed roles with an ongoing equipment-operations responsibility
    # (Administrator, Equipment Pool Staff) -- a minimal, required rename to
    # keep this existing feature working, not a redesign of it.
    result = await db.execute(
        select(User.id).join(Role, Role.id == User.role_id).where(
            Role.name.in_([ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF]), User.is_active.is_(True)
        )
    )
    return [user_id for (user_id,) in result.all()]


def _notify_recipients(db, recipient_ids, *, title: str, body: str, notif_type: str) -> None:
    for user_id in recipient_ids:
        db.add(Notification(user_id=user_id, type=notif_type, title=title, body=body))


async def check_pm_cal_due() -> None:
    # Roadmap PR14A (Backend Audit 16.1): the recipient list used to be
    # re-queried once per due equipment row (N+1). It is now loaded at most
    # once per run, and only once there is at least one PM- or CAL-due row
    # to notify about -- a run with nothing due performs zero recipient
    # queries.
    #
    # Roadmap PR15A: each scheduled run gets its own run_id (a background
    # job is not an HTTP request and must not be correlated via
    # request_id/correlation_id -- see app.core.log_context's docstring),
    # and any unhandled exception is logged with full context before
    # re-raising unchanged, so a failed run is no longer silent to
    # application logs (APScheduler's own internal error handling has no
    # visibility into this job's business context). No business logic
    # below this point changed.
    run_id = uuid.uuid4().hex
    run_id_token = job_run_id_var.set(run_id)
    start = time.monotonic()
    try:
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

            if not pm_due and not cal_due:
                await db.commit()
                logger.info(
                    "PM/CAL due check complete: 0 PM, 0 CAL",
                    extra={"duration_ms": round((time.monotonic() - start) * 1000, 2)},
                )
                return

            recipient_ids = await _get_recipient_ids(db)

            for eq in pm_due:
                _notify_recipients(
                    db,
                    recipient_ids,
                    title=f"PM ใกล้ครบกำหนด: {eq.equipment_name}",
                    body=f"เครื่อง {eq.asset_number} มีกำหนด PM วันที่ {eq.pm_due_date}",
                    notif_type="pm",
                )

            for eq in cal_due:
                _notify_recipients(
                    db,
                    recipient_ids,
                    title=f"Calibration ใกล้ครบกำหนด: {eq.equipment_name}",
                    body=f"เครื่อง {eq.asset_number} มีกำหนด Calibration วันที่ {eq.cal_due_date}",
                    notif_type="calibration",
                )

            await db.commit()
            logger.info(
                "PM/CAL due check complete: %d PM, %d CAL",
                len(pm_due),
                len(cal_due),
                extra={"duration_ms": round((time.monotonic() - start) * 1000, 2)},
            )
    except Exception:
        logger.exception(
            "PM/CAL due check failed",
            extra={"duration_ms": round((time.monotonic() - start) * 1000, 2)},
        )
        raise
    finally:
        job_run_id_var.reset(run_id_token)


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
