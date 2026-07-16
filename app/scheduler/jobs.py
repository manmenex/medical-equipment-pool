"""
Automatic recall-checking scheduler (FUNCTION 10).

Wraps APScheduler's `BackgroundScheduler` so the desktop app can run its
FDA/ECRI refresh + matching + report generation pipeline unattended, on a
daily, weekly or monthly cadence, without blocking the Qt event loop.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.models.enums import SchedulerFrequency
from app.services.app_context import AppContext
from app.services.period_service import get_current_period
from app.utils.exceptions import AppError
from app.utils.logging_config import get_audit_logger, get_logger

logger = get_logger(__name__)
audit_error = get_audit_logger("error")

JOB_ID = "recall_check_job"


def run_full_check(context: AppContext, notify: Optional[Callable[[str], None]] = None) -> None:
    """The unit of work executed on every scheduled firing (and by "Run Now").

    Refreshes FDA + ECRI data for the current weekly period, runs the
    matching engine, and writes an Excel + PDF report - exactly what a
    user would trigger manually from the Dashboard.
    """
    period = get_current_period()

    def _say(message: str) -> None:
        logger.info(message)
        if notify:
            notify(message)

    try:
        _say(f"Scheduled check starting for {period.label} ({period.start_date} to {period.end_date})")
        context.fda_service.refresh(period.start_date, period.end_date)

        if context.ecri_service.has_credentials():
            context.ecri_service.refresh(period.start_date, period.end_date)
        else:
            _say("Skipping ECRI refresh - no credentials configured yet.")

        outputs = context.report_service.generate_weekly_report(period.year, period.month, period.week_number)
        context.db.execute(
            "INSERT OR REPLACE INTO app_settings (key, value, updated_at) VALUES (?,?,?)",
            ("last_update", datetime.now().isoformat(), datetime.now().isoformat()),
        )
        _say(f"Scheduled check complete. Reports written: {list(outputs.values())}")
    except AppError as exc:
        audit_error.error("Scheduled check failed: %s", exc)
        _say(f"Scheduled check failed: {exc}")
    except Exception as exc:  # pragma: no cover - defensive catch-all
        audit_error.exception("Unexpected error during scheduled check")
        _say(f"Scheduled check failed unexpectedly: {exc}")


def _build_trigger(frequency: SchedulerFrequency, hour: int, minute: int) -> CronTrigger:
    if frequency == SchedulerFrequency.DAILY:
        return CronTrigger(hour=hour, minute=minute)
    if frequency == SchedulerFrequency.WEEKLY:
        return CronTrigger(day_of_week="mon", hour=hour, minute=minute)
    if frequency == SchedulerFrequency.MONTHLY:
        return CronTrigger(day=1, hour=hour, minute=minute)
    raise ValueError(f"Unsupported scheduler frequency: {frequency}")


class SchedulerManager:
    """Owns the single background scheduler instance for the app's lifetime."""

    def __init__(self, context: AppContext, notify: Optional[Callable[[str], None]] = None):
        self.context = context
        self.notify = notify
        self._scheduler = BackgroundScheduler()

    def configure(self, frequency: str, hour: int, minute: int) -> None:
        freq = SchedulerFrequency(frequency)
        trigger = _build_trigger(freq, hour, minute)
        if self._scheduler.get_job(JOB_ID):
            self._scheduler.remove_job(JOB_ID)
        self._scheduler.add_job(
            run_full_check, trigger=trigger, id=JOB_ID, args=[self.context, self.notify], replace_existing=True
        )
        logger.info("Scheduler configured: frequency=%s hour=%02d minute=%02d", frequency, hour, minute)

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("Scheduler started.")

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped.")

    def run_now(self) -> None:
        """Manually trigger the same job the scheduler would run automatically."""
        run_full_check(self.context, self.notify)

    @property
    def next_run_time(self):
        job = self._scheduler.get_job(JOB_ID)
        return job.next_run_time if job else None
