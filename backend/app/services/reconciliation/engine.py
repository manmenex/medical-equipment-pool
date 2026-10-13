"""Roadmap PR22C §5-§8 -- `execute_reconciliation_run`, the single
top-level entry point that claims a pending run, executes the
deterministic analysis engine against one consistent PostgreSQL
snapshot, and persists the result.

**Transaction design (§5/§7), mirroring `app.services.import_execution_
service.run_execute`'s established TX1/TX2/TX3 shape:**

- **TX1** (the caller-supplied `db` session): validation reads (run
  exists, `pending`, supported `rule_version`, bound coverage still
  matches the run's own copied values) plus the CAS claim itself
  (`pending -> running`, fenced on `expected_version`). Committed here,
  by this function -- not by a low-level helper.
- **TX2** (a fresh, independent session, `REPEATABLE READ`): the
  analysis proper -- one consistent snapshot read (`context.build_
  context`), every rule module evaluated against it, every finding +
  finding-event junction row persisted, and the fenced `running ->
  completed` transition, all inside this one transaction. If any of it
  raises, this whole transaction rolls back -- no partial finding set is
  ever left visible (§7/§26).
- **TX3** (only on a TX2 failure): a second fresh, independent session
  that attempts the fenced `running -> failed` transition. Fenced
  against `version == admitted_version` so a run a different worker has
  already legitimately advanced is never overwritten (§7) -- if the
  fence is lost, this is a silent no-op (the other worker's own outcome
  is authoritative) rather than a second, contradictory write.

TX2/TX3 are opened from a session factory built on `db.bind` -- the
exact same engine the caller's own `db` (TX1) is bound to -- never the
application's global `AsyncSessionLocal`. Importing that global default
directly would silently target `settings.DATABASE_URL` regardless of
what engine the caller actually passed in (e.g. a test's own isolated
PostgreSQL engine), which is both a correctness bug and untestable.

No low-level helper in this package (`context`, `projection`, the `rules`
package, `persistence`) ever calls `db.commit()`/`db.rollback()` -- only
this module does, and only at the three boundaries above.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import (
    ReconciliationAnalysisFailedError,
    ReconciliationRunNotFoundError,
    ReconciliationRunNotPendingError,
    ReconciliationRunVersionConflictError,
    UnsupportedReconciliationRuleVersionError,
)
from app.models.legacy_reconciliation import LegacyReconciliationRun

from . import persistence
from .context import build_context
from .coverage import verify_coverage_integrity
from .rule_version import PR22_RECONCILIATION_RULE_VERSION
from .rules import (
    bme_traceability,
    chronology,
    current_state,
    duplicates,
    equipment_identity,
    pairing,
    source_provenance,
    ward_traceability,
)

logger = logging.getLogger(__name__)

# §9: fixed, deterministic evaluation order -- irrelevant to the final
# persisted order (`persistence.sort_candidates` re-sorts by code, §11),
# but kept fixed anyway so this list itself is a stable, reviewable
# statement of "every rule this engine runs."
_RULES = (
    equipment_identity,
    source_provenance,
    duplicates,
    chronology,
    current_state,
    ward_traceability,
    bme_traceability,
    pairing,
)


async def _load_run(db: AsyncSession, run_id: uuid.UUID) -> LegacyReconciliationRun:
    run = (
        await db.execute(select(LegacyReconciliationRun).where(LegacyReconciliationRun.id == run_id))
    ).scalar_one_or_none()
    if run is None:
        raise ReconciliationRunNotFoundError(f"Reconciliation run '{run_id}' does not exist.")
    return run


async def _validate_and_claim(
    db: AsyncSession, *, run_id: uuid.UUID, expected_version: int
) -> tuple[LegacyReconciliationRun, uuid.UUID]:
    """§5 steps A-C, §38: read-only validation, then the CAS claim
    itself. Raises without any mutation on every validation failure;
    the CAS UPDATE is the only write TX1 ever issues."""
    run = await _load_run(db, run_id)

    if run.rule_version != PR22_RECONCILIATION_RULE_VERSION:
        raise UnsupportedReconciliationRuleVersionError(
            f"Run '{run_id}' was created for rule_version '{run.rule_version}', but this engine only "
            f"supports '{PR22_RECONCILIATION_RULE_VERSION}'. run.rule_version is never changed "
            "automatically -- create a new run under the current engine version instead."
        )

    if run.status != "pending":
        raise ReconciliationRunNotPendingError(
            f"Run '{run_id}' has status '{run.status}', not 'pending'. A completed or failed run is never "
            "re-executed (§27) -- create a new run instead."
        )

    # Shared with PR22E's sign-off precondition 4 (§19 of that task) --
    # `app.services.reconciliation.coverage.verify_coverage_integrity` is
    # the one place this fail-closed comparison is implemented.
    coverage = await verify_coverage_integrity(db, run=run)

    claim_result = await db.execute(
        update(LegacyReconciliationRun)
        .where(
            LegacyReconciliationRun.id == run_id,
            LegacyReconciliationRun.status == "pending",
            LegacyReconciliationRun.version == expected_version,
        )
        .values(status="running", version=LegacyReconciliationRun.version + 1, started_at=datetime.now(timezone.utc))
        .returning(LegacyReconciliationRun)
    )
    claimed = claim_result.scalar_one_or_none()
    if claimed is None:
        raise ReconciliationRunVersionConflictError(
            f"Run '{run_id}' was claimed by a concurrent caller, or expected_version {expected_version} is stale."
        )
    return claimed, coverage.migration_authority_id


async def _mark_failed(
    session_factory: async_sessionmaker[AsyncSession], *, run_id: uuid.UUID, expected_version: int
) -> None:
    """TX3 (§7): a fresh, independent session from the same engine as
    TX1/TX2. Fenced on `status == 'running' AND version ==
    expected_version` -- if a different worker already legitimately
    advanced this run past that version (e.g. by winning a later claim
    after a prior fence loss), this is a silent no-op, never a second,
    contradictory write."""
    try:
        async with session_factory() as tx3:
            await tx3.execute(
                update(LegacyReconciliationRun)
                .where(
                    LegacyReconciliationRun.id == run_id,
                    LegacyReconciliationRun.status == "running",
                    LegacyReconciliationRun.version == expected_version,
                )
                .values(
                    status="failed",
                    version=LegacyReconciliationRun.version + 1,
                    failed_at=datetime.now(timezone.utc),
                )
            )
            await tx3.commit()
    except Exception:
        logger.exception(
            "TX3 (fenced running->failed transition) for reconciliation run %s failed on infrastructure "
            "grounds; run left in 'running' state, no further automatic recovery",
            run_id,
        )


async def execute_reconciliation_run(
    db: AsyncSession, *, run_id: uuid.UUID, expected_version: int
) -> LegacyReconciliationRun:
    """§5. `db` is TX1's own session -- the caller (a future PR22D/E
    operator-facing service, or a test) owns it and everything about its
    lifecycle before/after this call; this function commits it exactly
    once, for the claim, and never touches it again afterward."""
    claimed_run, migration_authority_id = await _validate_and_claim(db, run_id=run_id, expected_version=expected_version)
    await db.commit()
    admitted_version = claimed_run.version

    # TX2/TX3 must observe the exact same database as TX1 -- built from
    # `db.bind` (TX1's own engine), never the application's global
    # default session factory.
    session_factory = async_sessionmaker(db.bind, expire_on_commit=False, class_=AsyncSession)

    try:
        async with session_factory() as tx2:
            # §6: REPEATABLE READ, set before this session's transaction
            # issues any statement -- every read inside this block
            # therefore shares one consistent PostgreSQL snapshot,
            # established by whichever SELECT runs first
            # (`context.build_context`'s own first query).
            await tx2.connection(execution_options={"isolation_level": "REPEATABLE READ"})

            context = await build_context(tx2, run=claimed_run, migration_authority_id=migration_authority_id)

            all_candidates: tuple = ()
            for rule in _RULES:
                all_candidates += rule.evaluate(context)

            summary = await persistence.persist_findings(
                tx2, run_id=run_id, rule_version=claimed_run.rule_version, candidates=all_candidates
            )

            complete_result = await tx2.execute(
                update(LegacyReconciliationRun)
                .where(
                    LegacyReconciliationRun.id == run_id,
                    LegacyReconciliationRun.status == "running",
                    LegacyReconciliationRun.version == admitted_version,
                )
                .values(
                    status="completed",
                    version=LegacyReconciliationRun.version + 1,
                    completed_at=datetime.now(timezone.utc),
                    summary_total_findings=summary.total_findings,
                    summary_high=summary.high,
                    summary_medium=summary.medium,
                    summary_low=summary.low,
                )
                .returning(LegacyReconciliationRun)
            )
            completed_run = complete_result.scalar_one_or_none()
            if completed_run is None:
                # §7: a fence loss here means a different caller mutated
                # this run between TX1's claim and this exact statement
                # -- structurally impossible under this engine's own
                # single-winner CAS unless something external raced it,
                # but handled explicitly rather than assumed away: no
                # finding is left visible (this whole transaction is
                # about to roll back with the exception below).
                raise ReconciliationRunVersionConflictError(
                    f"Run '{run_id}' was modified concurrently between claim and completion; this "
                    "transaction's own finding inserts are rolled back with it."
                )
            await tx2.commit()
            return completed_run
    except Exception as exc:
        logger.exception("Reconciliation analysis failed for run %s", run_id)
        await _mark_failed(session_factory, run_id=run_id, expected_version=admitted_version)
        raise ReconciliationAnalysisFailedError(f"Reconciliation analysis failed for run '{run_id}': {exc}") from exc
