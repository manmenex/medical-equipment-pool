"""Retention cleanup orchestration for the legacy-import pipeline.

Roadmap PR19A3 (docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md §18).
Implements the approved Owner Decision (docs/DECISION_LOG.md): 180-day
post-terminal retention, redact-in-place, deployment-configurable period,
no Version 1 Administrator UI. The endpoint, a scheduler, or a manual
operator call are merely invocation mechanisms -- correctness comes
entirely from the claim/fencing protocol in `app.crud.import_retention`,
regardless of who or how often it is invoked.
"""

import logging
import uuid

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AUDIT_ACTION_IMPORT_RETENTION_CLEANUP, AUDIT_ENTITY_IMPORT_SESSION, record_audit_event
from app.core.config import settings
from app.crud import import_retention as import_retention_crud
from app.services import import_lease

logger = logging.getLogger(__name__)


async def run_retention_cleanup(
    db: AsyncSession, *, actor_id: uuid.UUID | None, request: Request | None, limit: int
) -> dict:
    """§21 endpoint #12. Claims up to `limit` eligible terminal sessions
    (`app.crud.import_retention.claim_sessions_for_cleanup`), then
    redacts each one in its own fenced, all-or-nothing transaction
    (`redact_session`). A session whose redaction transaction fails for
    any reason, or whose claim was lost to another concurrent worker, is
    skipped and remains eligible for the next invocation (§18's "Retry
    and recovery") -- never retried inline within this same call."""
    worker_id = uuid.uuid4()
    session_ids = await import_retention_crud.claim_sessions_for_cleanup(
        db,
        worker_id=worker_id,
        retention_days=settings.IMPORT_RETENTION_DAYS,
        claim_timeout_seconds=settings.IMPORT_RETENTION_CLEANUP_CLAIM_TIMEOUT_SECONDS,
        limit=limit,
    )

    purged_count = 0
    skipped_count = 0
    for session_id in session_ids:
        try:
            redacted = await import_retention_crud.redact_session(db, session_id=session_id, worker_id=worker_id)
        except Exception:
            await db.rollback()
            logger.exception("Retention cleanup redaction for session %s failed; will be retried later", session_id)
            skipped_count += 1
            continue

        if redacted is None:
            # §18/§9.4.2's identical fence-loss contract: the claim was
            # reclaimed by another worker before this transaction could
            # commit -- roll back, report the loss, never overwrite.
            await db.rollback()
            await import_lease.write_fence_lost_audit(actor_id=actor_id, session_id=session_id, request=request)
            skipped_count += 1
            continue

        # §19: same fenced redaction transaction as the final
        # retention_purged_at/source_bytes_deleted_at UPDATE.
        await record_audit_event(
            db,
            actor_user_id=actor_id,
            action=AUDIT_ACTION_IMPORT_RETENTION_CLEANUP,
            entity_type=AUDIT_ENTITY_IMPORT_SESSION,
            entity_id=session_id,
            request=request,
        )
        await db.commit()
        purged_count += 1

    # §21: "has_more: true signals more eligible sessions exist beyond
    # this batch" -- a full-batch claim is the only honest signal this
    # single call can give; a partial claim means the eligible set was
    # exhausted (skipped sessions remain eligible for a *future*
    # invocation, not this one).
    has_more = len(session_ids) >= limit
    return {"purged_count": purged_count, "skipped_count": skipped_count, "has_more": has_more}
