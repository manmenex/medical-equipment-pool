import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.import_session import (
    ImportJob,
    ImportRowError,
    ImportSession,
    ImportSource,
    ImportSourceBlob,
)
from app.services.import_plan_provider import PlanProviderNotRegisteredError, get_plan_provider

# Roadmap PR19A3 (docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md §18).
# A genuinely new concurrency mechanism -- SELECT ... FOR UPDATE SKIP
# LOCKED -- unrelated to §9's job-lease apparatus (import_job.py), since
# retention cleanup claims a batch of *sessions*, not one job. Two
# statements per claim/redaction step, exactly like §9.3's recovery claim,
# so the pattern is familiar even though the underlying primitive differs.


async def claim_sessions_for_cleanup(
    db: AsyncSession, *, worker_id: uuid.UUID, retention_days: int, claim_timeout_seconds: int, limit: int
) -> tuple[list[uuid.UUID], bool]:
    """§18's atomic batch claim. On PostgreSQL, `SELECT ... FOR UPDATE
    SKIP LOCKED` takes a row lock on each eligible session before the
    fenced claim `UPDATE` that follows in the same transaction --
    two concurrent invocations can never claim the same session, the
    loser simply skips rows already locked elsewhere rather than
    blocking or double-claiming. On SQLite (dev/test only, no concurrent-
    worker guarantee -- the same documented limitation as
    `app.crud.transaction`'s own SQLite fallback), `skip_locked` is
    unsupported and simply omitted; the claim `UPDATE`'s own re-checked
    `WHERE` clause is still a correct, if non-concurrent-safe, guard.

    Selects up to `limit + 1` candidates so `has_more` can be determined
    without a separate `COUNT` query and without the boundary bug of
    treating "exactly `limit` eligible rows exist" as "more remain"
    (limit-plus-one pagination, matching this codebase's other cursor
    helpers, e.g. `app.crud.import_job.list_findings`): only the first
    `limit` candidates are ever claimed; the possible `limit + 1`th
    candidate's lock (taken only to prove its existence) is released
    unclaimed at this transaction's own commit, leaving it untouched and
    still eligible for a future call. Returns `(claimed_ids, has_more)`.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retention_days)
    dialect_name = db.get_bind().dialect.name

    eligible = (
        ImportSession.retention_purged_at.is_(None),
        ImportSession.terminal_at.isnot(None),
        ImportSession.terminal_at < cutoff,
        or_(
            ImportSession.retention_cleanup_claimed_by.is_(None),
            ImportSession.retention_cleanup_claim_expires_at < now,
        ),
    )

    select_stmt = select(ImportSession.id).where(*eligible).order_by(ImportSession.terminal_at.asc()).limit(limit + 1)
    if dialect_name == "postgresql":
        select_stmt = select_stmt.with_for_update(skip_locked=True)

    fetched_ids = [row[0] for row in (await db.execute(select_stmt)).all()]
    has_more = len(fetched_ids) > limit
    candidate_ids = fetched_ids[:limit]
    if not candidate_ids:
        await db.commit()
        return [], has_more

    result = await db.execute(
        update(ImportSession)
        .where(ImportSession.id.in_(candidate_ids), *eligible)
        .values(
            retention_cleanup_claimed_by=worker_id,
            retention_cleanup_claim_expires_at=now + timedelta(seconds=claim_timeout_seconds),
        )
        .returning(ImportSession.id)
    )
    claimed_ids = [row[0] for row in result.all()]
    await db.commit()
    return claimed_ids, has_more


async def redact_session(db: AsyncSession, *, session_id: uuid.UUID, worker_id: uuid.UUID) -> ImportSession | None:
    """§18's per-session redaction -- one all-or-nothing transaction,
    fenced on the claim. The first two `UPDATE`s redact descriptive/
    sensitive fields only (`checksum`/`error_code`/`severity`/`row_number`
    are never touched, so aggregate counts and identity remain
    reconcilable after redaction). The third `UPDATE` is the actual
    fencing check -- it only succeeds `WHERE retention_cleanup_claimed_by
    = :worker_id`, so a claim reclaimed by another worker (this one's
    `claim_timeout_seconds` expired) makes this whole transaction a
    no-op the caller must roll back, discarding the first two `UPDATE`s
    along with it. Returns `None` on that fence loss; the caller writes a
    single `AUDIT_ACTION_IMPORT_FENCE_LOST` entry in a separate TX3
    (§9.4.2's identical contract, reused here per §18's own reference to
    it). No commit -- the caller's own transaction, including the audit
    write on success, owns the boundary.

    Roadmap PR21-Foundation (design §38/§46): the leading `SELECT` below
    loads only the two columns the provider fail-closed decision needs
    (`dataset_type`, `dry_run_completed_at`) -- this session was not
    already loaded anywhere earlier in this call chain (`run_retention_
    cleanup` only has the claimed id), so this is one query per session,
    the same O(1)-per-session cost the final fenced `UPDATE ... RETURNING`
    below already pays, never a per-row or N+1 lookup."""
    session_meta = (
        await db.execute(
            select(ImportSession.dataset_type, ImportSession.dry_run_completed_at).where(ImportSession.id == session_id)
        )
    ).first()
    dataset_type = session_meta.dataset_type if session_meta is not None else None
    dry_run_completed_at = session_meta.dry_run_completed_at if session_meta is not None else None

    await db.execute(
        update(ImportSource).where(ImportSource.import_session_id == session_id).values(filename=None, content_type=None)
    )

    # Roadmap PR20A (design §6.6, fix round 2 H3R): one additional
    # same-transaction DELETE, not a second retention mechanism. Because
    # import_source_blobs lives in the same PostgreSQL database as every
    # other row this function already touches, this either commits with
    # the rest of this transaction or the whole transaction (redaction
    # included) rolls back together -- there is no intermediate state
    # where the metadata claims purged but the blob still exists. A no-op
    # for a session whose source never had a blob (every dataset_type that
    # doesn't use PR20A's upload endpoint).
    source_ids_subq = select(ImportSource.id).where(ImportSource.import_session_id == session_id)
    await db.execute(delete(ImportSourceBlob).where(ImportSourceBlob.import_source_id.in_(source_ids_subq)))

    job_ids_subq = select(ImportJob.id).where(ImportJob.import_session_id == session_id)
    await db.execute(
        update(ImportRowError)
        .where(ImportRowError.import_job_id.in_(job_ids_subq))
        .values(message="[redacted]", field=None)
    )

    # Roadmap PR21-Foundation (design §38/§46): fail-closed provider-owned
    # plan-artifact redaction, extending this same claimed/fenced
    # transaction -- not a third retention mechanism. A session can only
    # ever own a persisted plan artifact if it reached `dry_run_completed`
    # (the sole point `ImportAdapter.persist_dry_run_plan` is ever called,
    # in the same transaction as that fenced-completion write -- see that
    # method's own docstring), so `dry_run_completed_at IS NULL` is a
    # structural, not a registry-derived, proof that this session owns
    # nothing to redact here -- no provider lookup needed, matching every
    # dataset_type's retention behavior before this Foundation slice
    # existed. For a session that DID complete a dry-run, "no plan
    # provider registered for this dataset_type" is never read as "nothing
    # to redact": it fails closed (raises, letting this whole transaction,
    # including the core redaction already executed above, roll back) so
    # a genuinely provider-owned artifact can never be silently skipped.
    if dry_run_completed_at is not None:
        provider = get_plan_provider(dataset_type)
        if provider is None:
            raise PlanProviderNotRegisteredError(
                f"Session '{session_id}' completed a dry-run under dataset_type '{dataset_type}', but no "
                "DryRunPlanProvider is registered for that dataset_type -- retention cannot verify there is "
                "nothing provider-owned to redact, so this session's cleanup is left retryable."
            )
        await provider.redact_plan_artifacts(db, import_session_id=session_id)

    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(ImportSession)
        .where(ImportSession.id == session_id, ImportSession.retention_cleanup_claimed_by == worker_id)
        .values(notes=None, retention_purged_at=now, source_bytes_deleted_at=now)
        .returning(ImportSession)
    )
    return result.scalar_one_or_none()
