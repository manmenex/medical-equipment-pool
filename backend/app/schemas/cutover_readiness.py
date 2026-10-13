"""Roadmap PR23B -- Cutover Readiness Evidence Foundation. Explicit
Pydantic request/response contracts for every endpoint -- ORM models are
never reused as API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import UUIDStr

RunStatus = Literal["pending", "running", "completed", "failed"]
SourceOfTruthStrategy = Literal["hard_cutover"]


class RunListItem(BaseModel):
    """Review-relevant run metadata only -- never the raw ORM row."""

    id: UUIDStr
    status: RunStatus
    version: int
    created_by_user_id: UUIDStr
    created_at: datetime
    completed_at: datetime | None
    completed_by_user_id: UUIDStr | None
    application_baseline_sha: str
    database_migration_head: str
    source_of_truth_strategy: SourceOfTruthStrategy
    cutover_instant: datetime
    freeze_window_reference: str | None
    supersedes_run_id: UUIDStr | None

    model_config = {"from_attributes": True}


class RunDetail(RunListItem):
    equipment_master_import_source_id: UUIDStr | None
    legacy_migration_authority_id: UUIDStr | None
    legacy_coverage_id: UUIDStr | None
    reconciliation_run_id: UUIDStr | None
    reconciliation_signoff_id: UUIDStr | None
    current_state_verified_at: datetime | None
    current_state_verified_by_user_id: UUIDStr | None
    current_state_verification_scope_count: int | None
    current_state_verification_reference: str | None
    pilot_ward_id: UUIDStr | None
    operational_approver_reference: str | None


class RunCreateRequest(BaseModel):
    """POST request body. `application_baseline_sha` is supplied by the
    caller/deployment context (this module does not itself compute it)
    -- a machine-owned identity fact, never guessed or defaulted
    server-side beyond the length/domain constraints already enforced
    by the schema.

    **PR23B Fix Round 1: `database_migration_head` is deliberately NOT a
    field on this schema.** It must prove the actual database schema
    state at capture time, so it is always read server-side from
    `alembic_version` by `app.crud.cutover_readiness.
    _get_current_database_migration_head` -- never accepted from the
    request body. `model_config = {"extra": "forbid"}` (the same
    technique `EquipmentUpdate`/`BorrowRequest`/`ReturnRequest` already
    use for their own machine-owned fields) means a caller sending
    `database_migration_head` anyway gets a hard `422` via FastAPI's
    own centralized validation-error handling, never a silently-ignored
    field."""

    application_baseline_sha: str = Field(min_length=40, max_length=40)
    cutover_instant: datetime
    source_of_truth_strategy: SourceOfTruthStrategy = "hard_cutover"
    freeze_window_reference: str | None = Field(default=None, max_length=255)
    supersedes_run_id: UUIDStr | None = None

    model_config = {"extra": "forbid"}


class RunCompleteRequest(BaseModel):
    """POST .../complete request body. Every evidence reference the
    completion call needs -- deliberately excludes every machine-owned
    field (`status`, `completed_at`, `completed_by_user_id`, `version`
    itself as a written value) other than `expected_version`, the CAS
    guard. `model_config = {"extra": "forbid"}` for the same reason as
    `RunCreateRequest` above."""

    expected_version: int = Field(ge=0)
    equipment_master_import_source_id: UUIDStr
    legacy_migration_authority_id: UUIDStr
    legacy_coverage_id: UUIDStr
    reconciliation_run_id: UUIDStr
    reconciliation_signoff_id: UUIDStr
    current_state_verified_at: datetime
    current_state_verified_by_user_id: UUIDStr
    current_state_verification_scope_count: int | None = Field(default=None, ge=0)
    current_state_verification_reference: str | None = Field(default=None, max_length=255)
    pilot_ward_id: UUIDStr | None = None
    operational_approver_reference: str | None = Field(default=None, max_length=255)

    model_config = {"extra": "forbid"}


# Roadmap PR23C -- Readiness Gate Evaluation. §12 Gate G (Cutover
# authorization) is deliberately absent -- PR23D's own scope.
GateCode = Literal["A", "B", "C", "D", "E", "F"]
# §13 of the design -- the closed three-value category domain. Not a
# persisted enum (computed fresh on every call, never stored).
GateItemCategory = Literal["blocker", "warning", "info"]
GateStatus = Literal["blocker", "warning", "satisfied"]


class GateEvaluationItem(BaseModel):
    """One evaluation finding for one gate. `manual_attestation_required`
    is `True` only for sub-items this backend cannot verify from
    persisted evidence at all -- never set for a genuine computed
    pass/fail (see `app.services.cutover_readiness_gates`'s own module
    docstring, "Honesty over automation theater")."""

    gate: GateCode
    category: GateItemCategory
    code: str
    message: str
    manual_attestation_required: bool
    detail: dict

    model_config = {"from_attributes": True}


class GateSummary(BaseModel):
    """Per-gate roll-up: `blocker` if any BLOCKER item exists for this
    gate, else `warning` if any WARNING item exists, else `satisfied`.
    `mandatory` mirrors design §12/§13's own statement that Gates A-F
    are all mandatory (Gate D always; A/B/C/E by direct consequence of
    Gate D's dependency chain; F recommended mandatory)."""

    gate: GateCode
    mandatory: bool
    status: GateStatus


class GateEvaluationResponse(BaseModel):
    """`GET .../gate-evaluation` response. `has_blocker` is a
    convenience roll-up of `gates` -- `True` iff any gate's own
    `status == "blocker"`. This response is never persisted (§13) --
    computed fresh on every call against the run's evidence and the
    live database state at the moment of the call."""

    cutover_readiness_run_id: UUIDStr
    evaluated_at: datetime
    has_blocker: bool
    gates: list[GateSummary]
    items: list[GateEvaluationItem]


# Roadmap PR23D -- Go/No-Go Decision (§12 Gate G, §13). A different
# domain than `GateItemCategory` above -- this is the final decision
# *value*, never an Equipment lifecycle state (§40 of the task).
GoNoGoDecisionValue = Literal["GO", "NO_GO"]


class DecisionCreateRequest(BaseModel):
    """POST .../decision request body. `acknowledged_warning_codes` is
    only meaningful for `GO` (§13: "the approver must explicitly
    acknowledge each WARNING") -- ignored for `NO_GO`, which never
    requires or considers warnings. `no_go_reason` is a short, optional,
    operational text field only -- never authoritative readiness logic
    (see `app.models.cutover_readiness.CutoverGoNoGoDecision`'s own
    docstring). `model_config = {"extra": "forbid"}` for the same reason
    as `RunCreateRequest`/`RunCompleteRequest` above."""

    expected_version: int = Field(ge=0)
    decision: GoNoGoDecisionValue
    acknowledged_warning_codes: list[str] = Field(default_factory=list)
    no_go_reason: str | None = Field(default=None, max_length=2000)

    model_config = {"extra": "forbid"}


class DecisionDetail(BaseModel):
    """`POST`/`GET .../decision` response. Every field is server-derived
    -- no client-supplied trusted actor/timestamp. `acknowledged_warning_
    codes` reflects exactly what the backend recorded (the canonical,
    fresh-evaluation-derived set for `GO`; always `[]` for `NO_GO`),
    never the raw request payload."""

    id: UUIDStr
    cutover_readiness_run_id: UUIDStr
    decision: GoNoGoDecisionValue
    recorded_by_user_id: UUIDStr
    recorded_at: datetime
    run_version_at_decision: int
    acknowledged_warning_codes: list[str]
    no_go_reason: str | None

    model_config = {"from_attributes": True}
