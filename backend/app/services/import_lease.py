"""Shared, job-type-generic lease-renewal and fencing-audit helpers.

Roadmap PR19A3 (docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md §9.2,
§9.4.2, §19). Roadmap PR19A2's own `app.services.import_validation_service`
predates this module and keeps its own private, structurally-identical
copies of the renewal loop and the fence-lost-audit helper -- deliberately
left untouched here so that already-merged, independently-reviewed slice
is not modified by PR19A3's addition. This module exists so PR19A3's three
new call sites (dry-run, execute, retention cleanup) share one
implementation instead of a third and fourth private copy.
"""

import asyncio
import logging
import uuid

from fastapi import Request
from sqlalchemy.exc import DBAPIError

from app.core.audit import AUDIT_ACTION_IMPORT_FENCE_LOST, AUDIT_ENTITY_IMPORT_SESSION, record_audit_event
from app.crud import import_job as import_job_crud
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

_MAX_FAILURE_MESSAGE_LENGTH = 2000


async def renew_lease_loop(
    *, job_id: uuid.UUID, lease_owner: uuid.UUID, lease_generation: int, lease_duration_seconds: int, heartbeat_interval_seconds: int
) -> None:
    """§9.2, generic across `job_type` -- identical mechanism to
    `app.services.import_validation_service._renew_lease_loop`. Its own
    session, never the main work's. A clean 0-row renewal result is an
    unambiguous "lease lost" signal (stop immediately, no retry); a raised
    exception is treated as transient and retried up to two more times.
    This loop's own success or failure to notice a lost lease is only
    ever a best-effort, early-warning signal -- the real safety guarantee
    is completion fencing (§9.4), which works even if this loop never
    runs at all."""
    consecutive_transient_failures = 0
    while True:
        await asyncio.sleep(heartbeat_interval_seconds)
        try:
            async with AsyncSessionLocal() as db:
                renewed = await import_job_crud.renew_lease(
                    db,
                    job_id=job_id,
                    lease_owner=lease_owner,
                    lease_generation=lease_generation,
                    lease_duration_seconds=lease_duration_seconds,
                )
        except (OSError, DBAPIError):
            consecutive_transient_failures += 1
            if consecutive_transient_failures >= 3:
                return
            continue
        consecutive_transient_failures = 0
        if not renewed:
            return


def bound_failure_message(exc: Exception | None, *, phase_label: str) -> str:
    """Never persists the raw exception message or traceback (§22) -- an
    adapter may have echoed raw legacy source content into it. A generic,
    bounded, type-only description, labeled by phase so a validate/
    dry-run/execute/retention failure is distinguishable in the session's
    own `failure_reason`. The full exception is logged server-side only."""
    if exc is None:
        return f"{phase_label} failed: this attempt was superseded by a concurrent completion."
    return f"{phase_label} failed: {type(exc).__name__}."[:_MAX_FAILURE_MESSAGE_LENGTH]


async def write_fence_lost_audit(*, actor_id: uuid.UUID | None, session_id: uuid.UUID, request: Request | None) -> None:
    """§9.4.2 step 5 / §18 / §19: a separate, small transaction (TX3),
    opened strictly after the fenced attempt -- a job completion (dry-run,
    execute) or a retention-cleanup redaction -- has already failed and
    rolled back. Never causes or bypasses a fence -- it only ever reports
    one already confirmed lost."""
    async with AsyncSessionLocal() as tx3:
        await record_audit_event(
            tx3,
            actor_user_id=actor_id,
            action=AUDIT_ACTION_IMPORT_FENCE_LOST,
            entity_type=AUDIT_ENTITY_IMPORT_SESSION,
            entity_id=session_id,
            request=request,
        )
        await tx3.commit()
