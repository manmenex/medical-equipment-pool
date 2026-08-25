"""Roadmap PR23C -- Readiness Gate Evaluation.

Authoritative design: `docs/design/PR23_CUTOVER_READINESS_PLAN.md` §12
(Readiness Gates A-G), §13 (Go/No-Go, BLOCKER/WARNING/INFO), §16
(Concurrency/Freshness), §26 (OD-PR23-1/2/6, all RESOLVED / OWNER
APPROVED).

**Scope boundary (this slice only).** Evaluates Gates A-F against one
already-`completed` `CutoverReadinessRun`'s persisted evidence
references (PR23B) plus a small number of live re-checks against the
tables those references point at. **Read-only -- this module issues no
`INSERT`/`UPDATE`/`DELETE` anywhere, and no call site in this codebase
commits a transaction as a side effect of calling it.** Gate G (Cutover
authorization / the actual Go/No-Go decision) is explicitly out of
scope -- that is PR23D's own job (§27); this module never records a
decision, only ever reports evaluation items for a human (and, later,
PR23D) to act on.

**Never a second, PR23-owned computation of evidence PR20/21/22
already own.** Every gate below either re-reads an existing PR20/21/22
persisted fact (`ImportSession.status`, `LegacyReconciliationRun.
version`, `LegacyReconciliationSignOff.run_version_at_signoff`,
`LegacyReconciliationRun.supersedes_run_id`) or reuses PR23B's own
server-derived migration-head helper
(`app.crud.cutover_readiness.get_current_database_migration_head`) --
this module never re-derives BCM/Item Number integrity, Ward mapping,
or reconciliation finding/disposition counts itself (design §12 Gate B/
Gate D's own explicit instruction).

**Honesty over automation theater.** Several of §12's own listed
gate sub-items have **no corresponding persisted evidence anywhere in
this schema** -- "required PRs merged" (a fact about `docs/ROADMAP.md`,
not the database), CI status, production configuration, backup/restore
procedure (design §12: "currently undesigned"), staff training, manual
QR-workflow verification, and the issue/receive smoke test are all
real, mandatory readiness sub-items (§12), but none of them are
database-observable facts this service can prove true or false. This
module **never fabricates an automated pass** for any of these --
each is surfaced as an explicit `manual_attestation_required=True`
`WARNING` item (never silently omitted, never a fabricated `INFO`
"no gating effect" label, since these items DO gate Go per §12/§13),
so a human reviewer always sees exactly what was, and was not,
verified by software.

**Freshness is proven, not assumed (§16).** Two live re-checks exist
specifically because a run's persisted evidence can go stale between
capture and evaluation: (1) Gate A re-reads the database's *current*
migration head and compares it against the run's own captured
`database_migration_head` -- if the schema has moved on, that is a
genuine BLOCKER, not a false "everything is fine" carried forward from
capture time; (2) Gate D checks that the bound `LegacyReconciliationRun`
has not since been superseded (`supersedes_run_id` on some *other*
run pointing back at this one) and that `LegacyReconciliationSignOff.
run_version_at_signoff` still matches the run's own current `version`
-- both are re-read live, never assumed still true from PR23B's own
completion-time validation.

**No heuristic/fuzzy decisions.** Gate E (current-state readiness) is
reported `SATISFIED` once `current_state_verified_at`/`current_state_
verified_by_user_id` are present (PR23B's own completion-requires-
evidence `CHECK` already guarantees this for any `completed` run) --
this module deliberately does **not** invent an arbitrary "evidence is
older than N hours" staleness threshold; §16 itself explains why
equipment state changing between the readiness check and the Go
decision is expected and acceptable, not something a fixed time bound
could meaningfully police.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.cutover_readiness import get_current_database_migration_head
from app.models.cutover_readiness import CutoverReadinessRun
from app.models.import_session import ImportSession, ImportSource
from app.models.legacy_history import LegacyMigrationAuthority
from app.models.legacy_reconciliation import LegacyReconciliationRun, LegacyReconciliationSignOff
from app.services.import_adapters.equipment_master import DATASET_TYPE as EQUIPMENT_MASTER_DATASET_TYPE
from app.services.import_plan_providers.legacy_history import DATASET_TYPE as LEGACY_TRANSACTION_HISTORY_DATASET_TYPE

# §12/§13 of the design. "F" (Operational readiness) is included; "G"
# (Cutover authorization) is deliberately absent -- PR23D's own scope.
GATE_CODES = ("A", "B", "C", "D", "E", "F")

# §13 of the design -- the closed three-value category domain this
# module's own output is expressed in. Not a persisted enum (§13: "this
# document deliberately does not introduce a persisted enum/model for
# these categories") -- this module computes them fresh on every call,
# never stores them.
GATE_ITEM_CATEGORIES = ("blocker", "warning", "info")


@dataclass(frozen=True)
class GateItem:
    """One evaluation finding for one gate. `manual_attestation_required`
    is `True` only for the sub-items this module cannot verify from
    persisted evidence at all (see the module docstring's "Honesty over
    automation theater") -- never set for a genuine computed pass/fail."""

    gate: str
    category: str
    code: str
    message: str
    manual_attestation_required: bool = False
    detail: dict = field(default_factory=dict)


def _not_automated_item(*, gate: str, code: str, message: str) -> GateItem:
    return GateItem(
        gate=gate,
        category="warning",
        code=code,
        message=message,
        manual_attestation_required=True,
    )


async def _evaluate_gate_a(db: AsyncSession, run: CutoverReadinessRun) -> list[GateItem]:
    """§12 Gate A -- Application readiness. Only the migration-head
    freshness sub-item is database-observable; every other §12 Gate A
    sub-item (required PRs merged, CI green, production configuration,
    backup/restore procedure) has no persisted evidence anywhere in
    this schema and is reported as a `manual_attestation_required`
    item instead of a fabricated automated result."""
    items: list[GateItem] = []

    current_head = await get_current_database_migration_head(db)
    if current_head != run.database_migration_head:
        items.append(
            GateItem(
                gate="A",
                category="blocker",
                code="GATE_A_MIGRATION_HEAD_STALE",
                message=(
                    "The database's current migration head no longer matches this run's captured "
                    "database_migration_head evidence -- the schema has changed since this readiness "
                    "run was completed."
                ),
                detail={"captured_migration_head": run.database_migration_head, "current_migration_head": current_head},
            )
        )

    items.append(
        _not_automated_item(
            gate="A",
            code="GATE_A_REQUIRED_PRS_MERGED_NOT_AUTOMATED",
            message="Required Roadmap PRs merged (per docs/ROADMAP.md's Completed table) is not machine-verifiable "
            "by this service and requires manual confirmation.",
        )
    )
    items.append(
        _not_automated_item(
            gate="A",
            code="GATE_A_CI_GREEN_NOT_AUTOMATED",
            message="CI green on the exact deployed head is not machine-verifiable by this service and requires "
            "manual confirmation.",
        )
    )
    items.append(
        _not_automated_item(
            gate="A",
            code="GATE_A_PRODUCTION_CONFIG_NOT_AUTOMATED",
            message="Production configuration validation (real secrets, not defaults) is not machine-verifiable "
            "by this service and requires manual confirmation.",
        )
    )
    items.append(
        _not_automated_item(
            gate="A",
            code="GATE_A_BACKUP_RESTORE_NOT_AUTOMATED",
            message="Backup/restore procedure validation is not machine-verifiable by this service (and is "
            "currently undesigned per the design document) and requires manual confirmation.",
        )
    )
    return items


async def _evaluate_gate_b(db: AsyncSession, run: CutoverReadinessRun) -> list[GateItem]:
    """§12 Gate B -- Master data readiness. BCM/Item Number integrity and
    Ward mapping are enforced by PR20/PR21's own import-time validation,
    never re-derived here -- a `completed` import session is already
    proof of both, per the module docstring's "never a second, PR23-
    owned computation" discipline.

    **PR23C Fix Round 1.** `equipment_master_import_source_id` is only a
    UUID reference -- its field name does not by itself guarantee that
    the referenced `ImportSource` belongs to an Equipment Master
    `ImportSession`; a completed source/session for a *different*
    `dataset_type` (e.g. `legacy_transaction_history`) can otherwise be
    cross-wired into this field. Semantic dataset identity is only
    established by reading the owning session's own `dataset_type` and
    comparing it against `EQUIPMENT_MASTER_DATASET_TYPE` -- checked here
    independently of, and before, the completion check, since a wrong
    dataset and an incomplete import are different failure modes."""
    source = (
        await db.execute(select(ImportSource).where(ImportSource.id == run.equipment_master_import_source_id))
    ).scalar_one_or_none()
    if source is None:
        return [
            GateItem(
                gate="B",
                category="blocker",
                code="GATE_B_IMPORT_SOURCE_MISSING",
                message="The Equipment Master import source referenced by this run's evidence no longer exists.",
            )
        ]

    session = (
        await db.execute(select(ImportSession).where(ImportSession.id == source.import_session_id))
    ).scalar_one_or_none()
    if session is None:
        return [
            GateItem(
                gate="B",
                category="blocker",
                code="GATE_B_IMPORT_NOT_COMPLETED",
                message="The Equipment Master import session referenced by this run's evidence has not completed "
                "successfully.",
                detail={"import_session_status": None},
            )
        ]

    if session.dataset_type != EQUIPMENT_MASTER_DATASET_TYPE:
        return [
            GateItem(
                gate="B",
                category="blocker",
                code="GATE_B_WRONG_DATASET_TYPE",
                message="The import session referenced by this run's equipment_master_import_source_id evidence "
                "is not an Equipment Master import -- the referenced ImportSource belongs to a different "
                "dataset_type.",
                detail={
                    "expected_dataset_type": EQUIPMENT_MASTER_DATASET_TYPE,
                    "actual_dataset_type": session.dataset_type,
                },
            )
        ]

    if session.status != "completed":
        return [
            GateItem(
                gate="B",
                category="blocker",
                code="GATE_B_IMPORT_NOT_COMPLETED",
                message="The Equipment Master import session referenced by this run's evidence has not completed "
                "successfully.",
                detail={"import_session_status": session.status},
            )
        ]

    return [
        GateItem(
            gate="B",
            category="info",
            code="GATE_B_SATISFIED",
            message="Equipment Master import completed successfully.",
            detail={"import_session_id": str(session.id)},
        )
    ]


async def _evaluate_gate_c(db: AsyncSession, run: CutoverReadinessRun) -> list[GateItem]:
    """§12 Gate C -- Historical data readiness. `legacy_migration_
    authority_id` alone proves the workbook checksum was approved
    (PR21E0); it does not by itself prove any import actually executed
    against it, since `LegacyMigrationAuthority` is deliberately not the
    same identity as `ImportSource` (a same-file retry creates a fresh
    `ImportSource` each time -- see `app.models.legacy_history.
    LegacyMigrationAuthority`'s own docstring). This gate therefore also
    checks that at least one `legacy_transaction_history` import session
    completed using a source whose checksum matches the approved
    authority."""
    authority = (
        await db.execute(
            select(LegacyMigrationAuthority).where(LegacyMigrationAuthority.id == run.legacy_migration_authority_id)
        )
    ).scalar_one_or_none()
    if authority is None:
        return [
            GateItem(
                gate="C",
                category="blocker",
                code="GATE_C_AUTHORITY_MISSING",
                message="The legacy migration authority referenced by this run's evidence no longer exists.",
            )
        ]

    completed_import_exists = (
        await db.execute(
            select(
                exists().where(
                    ImportSource.checksum == authority.approved_workbook_sha256,
                    ImportSource.import_session_id == ImportSession.id,
                    ImportSession.dataset_type == LEGACY_TRANSACTION_HISTORY_DATASET_TYPE,
                    ImportSession.status == "completed",
                )
            )
        )
    ).scalar_one()
    if not completed_import_exists:
        return [
            GateItem(
                gate="C",
                category="blocker",
                code="GATE_C_IMPORT_NOT_COMPLETED",
                message="No completed legacy_transaction_history import was found for the approved workbook "
                "checksum referenced by this run's evidence.",
                detail={"approved_workbook_sha256": authority.approved_workbook_sha256},
            )
        ]

    return [
        GateItem(
            gate="C",
            category="info",
            code="GATE_C_SATISFIED",
            message="Legacy transaction history import completed successfully for the approved workbook checksum.",
        )
    ]


async def _evaluate_gate_d(db: AsyncSession, run: CutoverReadinessRun) -> list[GateItem]:
    """§12 Gate D -- Reconciliation readiness, restated from OD-PR22-6's
    four conditions. Conditions (1)-(3) (every finding dispositioned,
    zero `requires_correction`, a valid final sign-off exists) are
    already enforced, and never re-derived here, by PR22E's own sign-off
    preconditions (a `LegacyReconciliationSignOff` row cannot exist
    otherwise). This function checks only what can change *after* those
    preconditions were satisfied: whether the governing run has since
    been superseded (§16), and whether the run's own `version` still
    matches what the sign-off observed."""
    reconciliation_run = (
        await db.execute(
            select(LegacyReconciliationRun).where(LegacyReconciliationRun.id == run.reconciliation_run_id)
        )
    ).scalar_one_or_none()
    signoff = (
        await db.execute(
            select(LegacyReconciliationSignOff).where(
                LegacyReconciliationSignOff.id == run.reconciliation_signoff_id
            )
        )
    ).scalar_one_or_none()
    if reconciliation_run is None or signoff is None:
        return [
            GateItem(
                gate="D",
                category="blocker",
                code="GATE_D_EVIDENCE_MISSING",
                message="The reconciliation run or sign-off referenced by this run's evidence no longer exists.",
            )
        ]

    superseded = (
        await db.execute(
            select(exists().where(LegacyReconciliationRun.supersedes_run_id == reconciliation_run.id))
        )
    ).scalar_one()
    if superseded:
        return [
            GateItem(
                gate="D",
                category="blocker",
                code="GATE_D_RECONCILIATION_RUN_SUPERSEDED",
                message="The reconciliation run this readiness evidence was captured against has since been "
                "superseded by a newer run -- re-evaluate against the current governing run rather than trusting "
                "this stale snapshot.",
                detail={"reconciliation_run_id": str(reconciliation_run.id)},
            )
        ]

    if signoff.run_version_at_signoff != reconciliation_run.version:
        return [
            GateItem(
                gate="D",
                category="blocker",
                code="GATE_D_RECONCILIATION_RUN_VERSION_MISMATCH",
                message="The reconciliation run's own version no longer matches the version observed at sign-off "
                "time -- evidence integrity cannot be confirmed.",
                detail={
                    "run_version_at_signoff": signoff.run_version_at_signoff,
                    "current_run_version": reconciliation_run.version,
                },
            )
        ]

    return [
        GateItem(
            gate="D",
            category="info",
            code="GATE_D_SATISFIED",
            message="Reconciliation sign-off is valid, unsuperseded, and version-consistent.",
            detail={
                "reconciliation_run_id": str(reconciliation_run.id),
                "summary_total_findings": reconciliation_run.summary_total_findings,
                "summary_high": reconciliation_run.summary_high,
                "summary_medium": reconciliation_run.summary_medium,
                "summary_low": reconciliation_run.summary_low,
            },
        )
    ]


def _evaluate_gate_e(run: CutoverReadinessRun) -> list[GateItem]:
    """§12 Gate E -- Current-state readiness. `current_state_verified_at`/
    `current_state_verified_by_user_id` are guaranteed non-`NULL` for any
    `completed` run by PR23B's own `ck_cutover_readiness_runs_
    completion_requires_evidence` CHECK -- this function never
    re-verifies live equipment state itself (design §16: equipment state
    changing between the readiness check and the Go decision is expected
    and acceptable, not something a fixed time bound should police)."""
    return [
        GateItem(
            gate="E",
            category="info",
            code="GATE_E_SATISFIED",
            message="Current equipment state was manually/physically verified for this run.",
            detail={
                "current_state_verified_at": run.current_state_verified_at.isoformat()
                if run.current_state_verified_at
                else None,
                "current_state_verified_by_user_id": str(run.current_state_verified_by_user_id)
                if run.current_state_verified_by_user_id
                else None,
                "current_state_verification_scope_count": run.current_state_verification_scope_count,
            },
        )
    ]


def _evaluate_gate_f() -> list[GateItem]:
    """§12 Gate F -- Operational readiness. Entirely non-automatable --
    users/roles readiness, staff training, manual QR-workflow
    verification, the issue/receive smoke test, and rollback/contact
    responsibilities have no persisted evidence anywhere in this schema.
    """
    return [
        _not_automated_item(
            gate="F",
            code="GATE_F_USERS_ROLES_NOT_AUTOMATED",
            message="Users/roles readiness against the real production roster is not machine-verifiable by this "
            "service and requires manual confirmation.",
        ),
        _not_automated_item(
            gate="F",
            code="GATE_F_STAFF_TRAINING_NOT_AUTOMATED",
            message="Staff training on the application's terminology/workflow is not machine-verifiable by this "
            "service and requires manual confirmation.",
        ),
        _not_automated_item(
            gate="F",
            code="GATE_F_QR_WORKFLOW_NOT_AUTOMATED",
            message="QR workflow verification is not machine-verifiable by this service and requires manual "
            "confirmation.",
        ),
        _not_automated_item(
            gate="F",
            code="GATE_F_SMOKE_TEST_NOT_AUTOMATED",
            message="The issue/receive smoke test is not machine-verifiable by this service and requires manual "
            "confirmation.",
        ),
        _not_automated_item(
            gate="F",
            code="GATE_F_ROLLBACK_CONTACTS_NOT_AUTOMATED",
            message="Rollback/contact responsibilities being defined is not machine-verifiable by this service "
            "and requires manual confirmation.",
        ),
    ]


async def evaluate_gates(db: AsyncSession, *, run: CutoverReadinessRun) -> list[GateItem]:
    """§12/§13/§27 of the design. `run` must already be `status ==
    'completed'` -- the caller (the API layer) is responsible for that
    check; this function does not itself validate `run.status` so it
    stays a pure evaluation function over whatever evidence is present.
    Issues only `SELECT` statements -- never commits, never mutates."""
    items: list[GateItem] = []
    items.extend(await _evaluate_gate_a(db, run))
    items.extend(await _evaluate_gate_b(db, run))
    items.extend(await _evaluate_gate_c(db, run))
    items.extend(await _evaluate_gate_d(db, run))
    items.extend(_evaluate_gate_e(run))
    items.extend(_evaluate_gate_f())
    return items
