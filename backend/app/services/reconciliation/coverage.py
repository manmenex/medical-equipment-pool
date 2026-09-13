"""Roadmap PR22C/PR22E -- the single, shared coverage-integrity check.

Extracted (PR22E fix-round-free, up front) from what was inline logic in
`app.services.reconciliation.engine._validate_and_claim` (§38 of the
PR22C task) so PR22E's sign-off precondition 4 (§19/§9.J of the PR22E
task: the run's own copied `legacy_coverage_start`/`legacy_coverage_end`/
`live_system_start` must still match its bound `LegacyMigrationAuthority
Coverage` artifact) can reuse the exact same fail-closed comparison
rather than duplicating it. This module has no dependency on
`app.services.reconciliation.engine`'s own TX1/TX2/TX3 machinery -- it is
a single read-only query plus a comparison, safe to call from an HTTP
request transaction (PR22E's sign-off) without coupling that transaction
to analysis execution.

Never repairs or infers a mismatch -- a mismatch is always rejected, the
run/coverage rows are left completely untouched, and there is no
`MIN`/`MAX`-derived fallback (OD-PR22-7).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ReconciliationCoverageMismatchError
from app.models.legacy_reconciliation import LegacyMigrationAuthorityCoverage, LegacyReconciliationRun


async def verify_coverage_integrity(
    db: AsyncSession, *, run: LegacyReconciliationRun
) -> LegacyMigrationAuthorityCoverage:
    """Loads `run`'s bound coverage artifact and verifies its current
    `legacy_coverage_start`/`legacy_coverage_end`/`live_system_start`
    values still exactly match the run's own immutable copies. Raises
    `ReconciliationCoverageMismatchError` (never repairs) if the artifact
    no longer exists or the values have diverged."""
    coverage = (
        await db.execute(
            select(LegacyMigrationAuthorityCoverage).where(LegacyMigrationAuthorityCoverage.id == run.coverage_id)
        )
    ).scalar_one_or_none()
    if coverage is None:
        raise ReconciliationCoverageMismatchError(
            f"Run '{run.id}' references coverage '{run.coverage_id}', which no longer exists."
        )
    if (
        coverage.legacy_coverage_start != run.legacy_coverage_start
        or coverage.legacy_coverage_end != run.legacy_coverage_end
        or coverage.live_system_start != run.live_system_start
    ):
        raise ReconciliationCoverageMismatchError(
            f"Run '{run.id}''s own copied coverage timestamps no longer match its bound coverage artifact "
            f"'{coverage.id}'. Never repaired or inferred from MIN/MAX -- this run cannot execute or be signed off."
        )
    return coverage
