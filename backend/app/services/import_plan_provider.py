"""Internal dry-run-plan provider contract and registry.

Roadmap PR21-Foundation (docs/design/PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md
§29-§38, §46). This module is source-independent internal plumbing only --
it defines the shape a per-dataset "plan provider" must implement to (a)
back the existing PR20 static HTTP routes' read/confirm behavior and (b)
give the retention pipeline (`app.crud.import_retention.redact_session`) a
fail-closed hook for redacting provider-owned persisted plan artifacts. No
PR21-specific (legacy-history) provider is registered by this module or
anywhere else in this slice -- the only concrete provider that exists today
is `app.services.import_plan_providers.equipment_master`.

Deliberately a SEPARATE registry from `app.services.import_adapter`'s
`_ADAPTER_REGISTRY` (§30's "keep plan-provider responsibility separate from
parser/execution adapter responsibility"): a dataset_type's parser/executor
concern (`ImportAdapter`) and its persisted-plan-artifact concern
(`DryRunPlanProvider`) are independently registered, even though today's
only concrete implementation of each happens to be Equipment Master.

Fail-closed contract (§38, "datasets without provider artifacts"): a
dataset_type's plan provider is resolved from this registry only when the
session has actually completed a dry-run (`ImportSession.dry_run_completed_at
is not None`) -- the sole structural precondition under which
`ImportAdapter.persist_dry_run_plan` could ever have run (see that method's
own docstring: called "immediately after `plan_dry_run`'s read-only
evaluation succeeds ... in the same transaction as the session's
`dry_run_completed` fenced-completion write"). A session that never reached
`dry_run_completed_at` cannot possibly own a persisted plan artifact of any
kind, for any dataset_type, so the retention caller never needs a provider
for it. For a session that DID complete a dry-run, an unregistered provider
is never treated as "nothing to redact" -- callers must raise
`PlanProviderNotRegisteredError` and let the caller's transaction roll back
(fail closed) rather than silently skipping redaction. A dataset_type that
genuinely owns no provider-specific persisted artifacts declares that fact
by registering a `DryRunPlanProvider` whose `redact_plan_artifacts` is a
true no-op -- the explicit registration itself is the declaration; missing
registration is never read as proof of "nothing to redact".
"""

from __future__ import annotations

import abc
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


class PlanProviderError(RuntimeError):
    """Base class for this module's internal-only errors. Never mapped to
    an HTTP status code -- these propagate only to internal callers
    (retention's generic exception handling; a future PR20-route-
    integration call site), never directly to a FastAPI response."""


class PlanProviderAlreadyRegisteredError(PlanProviderError):
    """Raised by `register_plan_provider` when a `dataset_type` already has
    a registered provider -- duplicate registration fails clearly and
    immediately, never silently overwriting the earlier provider."""


class PlanProviderNotRegisteredError(PlanProviderError):
    """Raised by callers that require a provider for a `dataset_type` and
    find none registered (e.g. retention's fail-closed redaction hook, for
    a session that completed a dry-run under a `dataset_type` with no
    registered plan provider). Never silently interpreted as "nothing to
    redact" -- see this module's docstring."""


@dataclass(frozen=True)
class PlanSummaryRecord:
    """Provider-neutral mirror of `app.schemas.import_session.DryRunPlanSummaryOut`'s
    fields -- kept as a plain internal dataclass (not the Pydantic schema
    itself) so this service layer never imports the HTTP response-model
    module (§29's layering: routes -> schemas -> provider -> CRUD, never
    the reverse)."""

    total_rows: int
    creates: int
    updates: int
    skips: int
    warnings: int
    blocking_conflicts: int


@dataclass(frozen=True)
class PlanRecord:
    """Provider-neutral mirror of the persisted plan header fields
    `DryRunPlanOut`/`DryRunPlanConfirmOut` expose. `raw` carries the
    provider's own underlying persisted object (e.g. the
    `EquipmentMasterDryRunPlan` ORM row) for a caller that still needs
    dataset-specific fields this generic shape does not carry -- never
    interpreted or type-checked by this module itself."""

    id: uuid.UUID
    import_session_id: uuid.UUID
    import_source_id: uuid.UUID
    status: str
    created_at: datetime
    confirmed_at: datetime | None
    confirmed_by_user_id: uuid.UUID | None
    summary: PlanSummaryRecord
    raw: Any = None


@dataclass(frozen=True)
class PlanRowRecord:
    """Provider-neutral mirror of `DryRunPlanRowOut`'s fields."""

    id: uuid.UUID
    source_row_number: int
    action: str
    target_equipment_id: uuid.UUID | None
    normalized_values: dict[str, Any] | None
    matched_identity_fields: dict[str, Any] | None
    expected_equipment_version: int | None
    warnings: list[dict[str, Any]] | None


@dataclass
class PlanConfirmationResult:
    """Provider-neutral mirror of `app.crud.import_dry_run_plan.ConfirmationResult`
    -- `newly_confirmed` lets a caller gate a confirmation audit event
    exactly once per genuine first confirmation (§35)."""

    plan: PlanRecord
    newly_confirmed: bool


class DryRunPlanProvider(abc.ABC):
    """§30's internal provider contract. A concrete subclass is
    responsible for one `dataset_type`'s persisted dry-run-plan artifacts.

    Every method receives the session's already-loaded `import_session_id`
    (never a client-supplied dataset discriminator) -- provider selection
    happens once, by the caller, via `get_plan_provider(dataset_type)`."""

    #: Overridden by a concrete subclass -- the `dataset_type` string this
    #: provider handles (matches `import_sessions.dataset_type`).
    dataset_type: str

    @abc.abstractmethod
    async def get_current_plan(self, db: AsyncSession, *, import_session_id: uuid.UUID) -> PlanRecord | None:
        """Resolve the session's single current (`active`) plan, or
        `None` if the session has never had a successful dry-run."""

    @abc.abstractmethod
    async def list_plan_rows(
        self,
        db: AsyncSession,
        *,
        plan_id: uuid.UUID,
        limit: int,
        cursor_n: int | None,
        cursor_id: uuid.UUID | None,
    ) -> tuple[list[PlanRowRecord], int]:
        """Cursor-paginated rows for one plan, plus the plan's total row
        count -- mirrors `app.crud.import_dry_run_plan.list_plan_rows`'s
        limit-plus-one, integer-cursor contract exactly."""

    @abc.abstractmethod
    async def confirm_plan(
        self,
        db: AsyncSession,
        *,
        plan_id: uuid.UUID,
        import_session_id: uuid.UUID,
        current_user_id: uuid.UUID,
    ) -> PlanConfirmationResult:
        """Confirm exactly the plan identified by `plan_id`, atomically,
        preserving first-confirmation-wins semantics (§35). Must raise the
        same stale/not-found domain errors the wrapped dataset-specific CRUD
        already raises -- this method never translates or reinterprets
        them."""

    @abc.abstractmethod
    async def redact_plan_artifacts(self, db: AsyncSession, *, import_session_id: uuid.UUID) -> None:
        """§38's fail-closed retention hook. Called inside the caller's own
        (retention's) transaction -- must never call `db.commit()`/
        `db.rollback()` itself, only `db.execute()`/`db.flush()`. A no-op
        is a valid, deliberate implementation for a dataset_type that
        genuinely has nothing to redact (still requires this method to be
        registered and called, not skipped -- the no-op behavior is what
        makes the "no artifacts" declaration explicit, per this module's
        docstring)."""


_PLAN_PROVIDER_REGISTRY: dict[str, DryRunPlanProvider] = {}


def register_plan_provider(provider: DryRunPlanProvider) -> None:
    if provider.dataset_type in _PLAN_PROVIDER_REGISTRY:
        raise PlanProviderAlreadyRegisteredError(
            f"A DryRunPlanProvider is already registered for dataset_type '{provider.dataset_type}'."
        )
    _PLAN_PROVIDER_REGISTRY[provider.dataset_type] = provider


def unregister_plan_provider(dataset_type: str) -> None:
    _PLAN_PROVIDER_REGISTRY.pop(dataset_type, None)


def get_plan_provider(dataset_type: str) -> DryRunPlanProvider | None:
    return _PLAN_PROVIDER_REGISTRY.get(dataset_type)
