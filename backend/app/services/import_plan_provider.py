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

PR100-H1 fix round: earlier revisions of this module defined shared
`PlanRecord`/`PlanRowRecord`/`PlanSummaryRecord`/`PlanConfirmationResult`
dataclasses that mirrored Equipment Master's own field vocabulary
(`creates`/`updates`/`skips`, `target_equipment_id`,
`matched_identity_fields`, ...). That was a lossy common model in
disguise -- exactly the shape §31's "no dynamic dispatch, no generic
envelope" prohibition and §32's "dataset-specific plan/row contract" are
written against. `DryRunPlanProvider` is now `Generic[PlanT, RowT, ConfirmT]`
-- Foundation carries a provider's plan/row/confirmation objects through
completely opaquely (never reads a field off them, never constructs one).
A provider is free to return its own already-existing domain objects
directly (Equipment Master returns the real `EquipmentMasterDryRunPlan`/
`EquipmentMasterDryRunPlanRow` ORM rows and the CRUD layer's own
`ConfirmationResult` unchanged) -- no parallel mapping layer, no
translation step that could silently drop or misrepresent a field.

PR100-H2 fix round: `list_plan_rows` now requires the caller's own
`import_session_id` alongside `plan_id` and validates plan ownership
(`app.crud.import_dry_run_plan.get_plan_by_id`'s existing ownership-checked
lookup) *before* any pagination happens -- a `plan_id` that exists but
belongs to a different session is rejected exactly like it already is
everywhere else in this pipeline (confirm, redaction), never silently
listed. Pagination itself now uses an opaque cursor token
(`encode_plan_row_cursor`/`decode_plan_row_cursor`) that embeds the
`plan_id` it was issued for, so a cursor obtained while paging Plan A can
never be replayed against Plan B -- decoding validates the embedded
`plan_id` against the request's own `plan_id` before the cursor's sort
position is ever used. Because `plan_id` is already ownership-validated
against `import_session_id` earlier in the same call, binding the cursor to
`plan_id` transitively binds it to the owning session too, without needing
to duplicate `import_session_id` inside the cursor payload itself.
"""

from __future__ import annotations

import abc
import base64
import json
import uuid
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidInputError

PlanT = TypeVar("PlanT")
RowT = TypeVar("RowT")
ConfirmT = TypeVar("ConfirmT")


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
class Page(Generic[RowT]):
    """Provider-neutral pagination envelope. Contains only genuinely
    generic pagination metadata (§4's "may be shared" list) -- never a
    domain field belonging to any particular dataset_type's row shape.
    `next_cursor` is an opaque token (see `encode_plan_row_cursor`), never
    a raw sort-key tuple a caller could reinterpret against a different
    plan."""

    rows: list[RowT]
    total: int
    next_cursor: str | None


@dataclass(frozen=True)
class PlanRowCursor:
    """Decoded form of an opaque plan-row pagination cursor. `plan_id` is
    the identity binding PR100-H2 requires: a cursor decoded here carries
    the exact plan it was issued for, so a caller can (and must) reject it
    outright if it does not match the plan currently being paged, before
    ever touching `sort_value`/`row_id`."""

    plan_id: uuid.UUID
    sort_value: int
    row_id: uuid.UUID


def encode_plan_row_cursor(*, plan_id: uuid.UUID, sort_value: int, row_id: uuid.UUID) -> str:
    """Same base64/JSON technique as `app.utils.pagination`'s cursor
    codecs, extended with an embedded `plan_id` -- a plain `(sort_value,
    row_id)` tuple (that module's existing shape) carries no identity a
    decoder could validate against the plan currently being listed, which
    is exactly the gap PR100-H2 closes."""
    raw = json.dumps({"p": str(plan_id), "n": sort_value, "id": str(row_id)})
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_plan_row_cursor(cursor: str) -> PlanRowCursor:
    """Mirrors `app.utils.pagination.decode_int_cursor`'s malformed-input
    handling exactly (same exception types, same wrapped `InvalidInputError`
    outcome) -- a client-supplied cursor is untrusted input regardless of
    which module owns its encoding."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        data: dict[str, Any] = json.loads(raw)
        sort_value = data["n"]
        if not isinstance(sort_value, int) or isinstance(sort_value, bool):
            raise ValueError("cursor's integer sort field is not an integer")
        return PlanRowCursor(plan_id=uuid.UUID(data["p"]), sort_value=sort_value, row_id=uuid.UUID(data["id"]))
    except (ValueError, TypeError, KeyError) as exc:
        raise InvalidInputError("Invalid or malformed pagination cursor.") from exc


class DryRunPlanProvider(abc.ABC, Generic[PlanT, RowT, ConfirmT]):
    """§30's internal provider contract. A concrete subclass is
    responsible for one `dataset_type`'s persisted dry-run-plan artifacts.

    `PlanT`/`RowT`/`ConfirmT` are provider-owned, opaque to this module --
    Foundation never reads a field off them (PR100-H1). A provider is free
    to return its own pre-existing domain objects (ORM rows, an existing
    CRUD-layer result dataclass, ...) directly; nothing here prescribes a
    shared shape beyond genuinely generic pagination metadata (`Page`).

    Every method receives the session's already-loaded `import_session_id`
    (never a client-supplied dataset discriminator) -- provider selection
    happens once, by the caller, via `get_plan_provider(dataset_type)`."""

    #: Overridden by a concrete subclass -- the `dataset_type` string this
    #: provider handles (matches `import_sessions.dataset_type`).
    dataset_type: str

    @abc.abstractmethod
    async def get_current_plan(self, db: AsyncSession, *, import_session_id: uuid.UUID) -> PlanT | None:
        """Resolve the session's single current (`active`) plan, or
        `None` if the session has never had a successful dry-run."""

    @abc.abstractmethod
    async def list_plan_rows(
        self,
        db: AsyncSession,
        *,
        import_session_id: uuid.UUID,
        plan_id: uuid.UUID,
        limit: int,
        cursor: str | None,
    ) -> Page[RowT]:
        """Cursor-paginated rows for one plan. PR100-H2: implementations
        must validate that `plan_id` actually belongs to `import_session_id`
        (the same ownership check `confirm_plan`/`redact_plan_artifacts`
        already rely on) *before* listing anything, and must validate that
        a supplied `cursor` was issued for this exact `plan_id` before using
        its sort position -- a `plan_id` from a foreign session, or a
        cursor obtained while paging a different plan, must never silently
        return rows."""

    @abc.abstractmethod
    async def confirm_plan(
        self,
        db: AsyncSession,
        *,
        plan_id: uuid.UUID,
        import_session_id: uuid.UUID,
        current_user_id: uuid.UUID,
    ) -> ConfirmT:
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


_PLAN_PROVIDER_REGISTRY: dict[str, "DryRunPlanProvider[Any, Any, Any]"] = {}


def register_plan_provider(provider: "DryRunPlanProvider[Any, Any, Any]") -> None:
    if provider.dataset_type in _PLAN_PROVIDER_REGISTRY:
        raise PlanProviderAlreadyRegisteredError(
            f"A DryRunPlanProvider is already registered for dataset_type '{provider.dataset_type}'."
        )
    _PLAN_PROVIDER_REGISTRY[provider.dataset_type] = provider


def unregister_plan_provider(dataset_type: str) -> None:
    _PLAN_PROVIDER_REGISTRY.pop(dataset_type, None)


def get_plan_provider(dataset_type: str) -> "DryRunPlanProvider[Any, Any, Any] | None":
    return _PLAN_PROVIDER_REGISTRY.get(dataset_type)
