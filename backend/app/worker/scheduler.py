import logging
from datetime import date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.equipment import Equipment
from app.models.notification import Notification
from app.models.transaction import BorrowTransaction, TransactionStatus
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


async def check_overdue_returns() -> None:
    async with AsyncSessionLocal() as db:
        from datetime import datetime

        now = datetime.utcnow()
        overdue = (
            await db.execute(
                select(BorrowTransaction).where(
                    BorrowTransaction.status == TransactionStatus.OPEN,
                    BorrowTransaction.due_at.is_not(None),
                    BorrowTransaction.due_at < now,
                )
            )
        ).scalars().all()
        for tx in overdue:
            # Roadmap PR7 (knowledge/adr/ADR-005-transaction-model.md): the
            # transaction lifecycle has exactly two states, OPEN and CLOSED --
            # "overdue" is no longer a status value. An overdue transaction is
            # still OPEN (it has not been received); this job now only
            # notifies engineers and leaves status untouched, rather than
            # writing a third, no-longer-valid status.
            await _notify_engineers(
                db,
                title=f"เครื่องมือเกินกำหนดคืน: {tx.transaction_no}",
                body=f"ผู้ยืม {tx.borrower_name} ควรคืนภายใน {tx.due_at}",
                notif_type="overdue",
            )
        await db.commit()
        logger.info("Overdue check complete: %d overdue", len(overdue))


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(check_pm_cal_due, "cron", hour=6, minute=0, id="pm_cal_due_check")
    _scheduler.add_job(check_overdue_returns, "cron", hour="*", minute=0, id="overdue_check")
    _scheduler.start()
    logger.info("Scheduler started")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
