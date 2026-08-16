"""Parser adapter contract for the legacy-import pipeline.

Roadmap PR19A2 (docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md §10,
§11). No concrete adapter for a real legacy dataset (Equipment Master,
Receive History, Issue History) exists in this repository -- those are
PR20/PR21's deliverables (§26). This module defines only the abstract
contract and a registry; production ships with an empty registry, so
`get_adapter()` returns `None` for every real `dataset_type` until a
future slice registers one.
"""

from __future__ import annotations

import abc
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

# §10: unchanged from Roadmap PR12's precedent -- the bound is checked
# immediately after parse() returns, before any further work.
MAX_IMPORT_ROWS = 5000


@dataclass(frozen=True)
class RawImportRecord:
    """One parsed row, before business-rule validation. `row_number` is
    1-based and matches the source file's own row numbering (never a
    0-based array index) so a `ValidationFinding.row_number` is directly
    meaningful to an operator inspecting the original source. `fields` is
    an adapter-defined, already-typed mapping -- this module does not
    prescribe its shape beyond "typed and testable" (§10)."""

    row_number: int
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DryRunPlan:
    """Roadmap PR19A3 (design §16). The opaque result of a read-only
    evaluation, computed entirely within `plan_dry_run`'s read-only
    transaction, then discarded -- never persisted itself (only whether
    evaluation succeeded or raised feeds `session.dry_run_completed_at`/
    `status`, via the normal fenced-completion contract, §9.4.3).
    Deliberately minimal in this foundation; a future concrete-adapter
    slice may populate `summary` with adapter-defined preview content
    without changing this contract."""

    summary: dict[str, Any] = field(default_factory=dict)


class AdapterExecutionConflict(RuntimeError):
    """Roadmap PR20E (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md
    §14.4b). Raised by `execute()` to signal a genuine execution-time
    conflict that must also mark an adapter-owned sub-resource `failed`,
    inside the same TX2 write the framework already performs on any
    execute failure. `resolved_resource_id` is an opaque, adapter-defined
    primitive (never an ORM object -- TX1 has already rolled back by the
    time it is consumed, so any ORM-bound reference `execute()` held is
    detached/invalid) -- the framework never interprets its value, only
    passes it back to the adapter's own `on_execution_failure` hook.
    `None` means either no resource was resolved yet, or the raising
    adapter doesn't use this mechanism -- `on_execution_failure` is still
    called with `None` and its default no-op implementation does
    nothing."""

    def __init__(self, message: str, resolved_resource_id: uuid.UUID | None = None) -> None:
        super().__init__(message)
        self.resolved_resource_id = resolved_resource_id


@dataclass(frozen=True)
class FieldError:
    """One business-rule validation finding for one record, before it is
    persisted as an `ImportRowError` row (§4.4). `severity` must be
    exactly `"error"` or `"warning"` (§13) -- enforced by the caller that
    persists it (`ck_import_row_errors_severity`), not by this dataclass."""

    field: str | None
    error_code: str
    message: str
    severity: str = "error"


class ImportAdapter(abc.ABC):
    """§10/§11's abstract adapter contract. A concrete subclass is
    responsible for one `dataset_type`.

    `parse()` remains synchronous by design (§10: "real parsers are
    inherently sync/CPU-bound libraries") -- the caller invokes it via
    `asyncio.to_thread`, never directly on the event loop.

    The business-validation hook is deliberately split in two (§11), a
    structural guarantee against per-record queries, not a convention:
    `preload_business_context` is the only place a subclass may touch the
    database, called exactly once per validation pass;
    `validate_business_rules` receives no session parameter at all, so a
    per-record query is not merely discouraged -- it is impossible without
    an adapter smuggling its own out-of-band connection, which is a
    documented adapter-contract violation (§22's implementation invariant
    table, "Adapter writes outside the provided session").
    """

    #: Overridden by a concrete subclass -- the `dataset_type` string this
    #: adapter handles (matches `import_sessions.dataset_type`).
    dataset_type: str

    #: §12: recorded on the job at run time. A subclass may override this
    #: class attribute; the default is deliberately the string `"1"`, not
    #: an integer -- ruleset versions are opaque labels, not orderable.
    ruleset_version: str = "1"

    @abc.abstractmethod
    def parse(self, raw_input: Any) -> list[RawImportRecord]:
        """Synchronous, CPU-bound parse of `raw_input` into typed records,
        in deterministic (source-file) row order. `raw_input` is always
        `None` in this foundation -- no code in PR19A1-A3 stores or
        re-reads raw source bytes (§3.2, §3.6); a future concrete-adapter
        slice that adds byte storage will thread the real bytes through
        this same call site, unchanged."""

    async def preload_business_context(self, db: AsyncSession, records: list[RawImportRecord]) -> object:
        """Called exactly once per validation pass, before the per-record
        loop. Default: no bulk lookups, returns `None`. A concrete adapter
        performs its bulk lookups here (mirroring Roadmap PR12's
        bulk-lookup precedent) and returns an adapter-defined context
        object for `validate_business_rules` to consume."""
        return None

    @abc.abstractmethod
    def validate_business_rules(self, record: RawImportRecord, context: object) -> list[FieldError]:
        """Synchronous. Receives only the record and the context
        `preload_business_context` returned -- no database session
        parameter, structurally preventing a per-record query."""

    async def plan_dry_run(self, db: AsyncSession) -> "DryRunPlan":
        """Roadmap PR19A3 (design §16). Called against a **separate**,
        genuinely read-only `AsyncSession` (`SET TRANSACTION READ ONLY` on
        PostgreSQL) -- any write attempt is rejected by the database
        itself. Default: not implemented. Deliberately a concrete default
        that raises, not `abc.abstractmethod` -- an adapter that only
        implements `parse`/`validate_business_rules` (validate-only) is
        still a valid, registrable adapter; the service layer detects a
        non-overriding subclass before ever admitting a dry-run attempt
        and responds `501 IMPORT_ADAPTER_NOT_IMPLEMENTED` (§23), never by
        calling this default and catching the exception."""
        raise NotImplementedError

    async def persist_dry_run_plan(self, db: AsyncSession, plan: "DryRunPlan") -> None:
        """Roadmap PR20D (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md
        §14.3, §6.3). Called by the framework on the normal *writable*
        session, immediately after `plan_dry_run`'s read-only evaluation
        succeeds and closes, in the same transaction as the session's
        `dry_run_completed` fenced-completion write. Default: a no-op --
        an adapter that has nothing to persist (every adapter that
        predates this mechanism, and any future adapter with no
        persisted-plan concept of its own) is unaffected."""
        return

    async def precheck_execute(self, db: AsyncSession) -> None:
        """Roadmap PR20E (design §14.4a). Called by the framework in
        `run_execute`, **before** `admit_phase_job` runs, on a read-only
        basis -- never mutates anything, so a caller may run this on
        either session type. Session/source identity via the same
        contextvar (§6.4) `execute()` itself uses. Default: a no-op --
        an adapter with no persisted-plan concept of its own (every
        adapter that predates this mechanism) is unaffected. A concrete
        override raises a structural, non-mutating rejection (its own
        domain error) if execution cannot possibly succeed for a reason
        knowable before any session state changes -- e.g. no confirmed
        plan exists yet -- so the framework can surface a cheap,
        retryable 4xx before ever touching `import_sessions`/
        `import_jobs`."""
        return

    async def execute(self, db: AsyncSession) -> int:
        """Roadmap PR19A3 (design §17). Called against the normal,
        read-write session, inside the single-winner execution's own `TX1`
        (§9.4.1) -- unlike `plan_dry_run`, this must actually write.
        Returns the number of rows imported (persisted as
        `import_sessions.imported_rows`). Must never call `db.commit()`/
        `db.rollback()` itself -- the caller owns `TX1`'s transaction
        boundary (§22's adapter-contract invariant: "adapter writes
        outside the provided session" is a documented obligation this
        foundation cannot force a misbehaving adapter to comply with, but
        never itself violates). Default: not implemented -- see
        `plan_dry_run`'s docstring for the same rationale. May raise
        `AdapterExecutionConflict` to carry a `resolved_resource_id`
        through TX1's rollback into `on_execution_failure` (§14.4b),
        rather than a bare exception, whenever a genuine execution-time
        conflict must also mark an adapter-owned sub-resource `failed`.

        Roadmap PR20E fix round 2 (PR #95 review, §H1/§H2): an adapter
        with a persisted execution-time sub-resource (e.g. PR20's
        confirmed DryRunPlan) must call `app.services.import_adapter_
        context.record_resolved_execution_resource(resource_id)`
        immediately after resolving that resource, *before* attempting
        any mutation -- never at the end, and never only inside an
        exception handler. This makes the resolved id available to the
        framework unconditionally, on both the success and failure
        return paths, for the rest of TX1 and for TX2 failure
        publication. It must never mutate that sub-resource itself
        (e.g. mark a plan `consumed`) -- that transition belongs to
        `on_execution_success` below, called only after the framework's
        own Job/Session completion fence has already succeeded, so the
        global lock order stays Job -> Session -> resource, matching
        recovery and TX2 failure publication exactly."""
        raise NotImplementedError

    async def on_execution_success(self, db: AsyncSession, resolved_resource_id: uuid.UUID | None) -> None:
        """Roadmap PR20E fix round 2 (PR #95 review, §H1). Called by the
        framework on TX1's own session, immediately after
        `fenced_phase_success` has already succeeded (the Job/Session
        completion fence is locked and about to commit) but *before*
        TX1's own commit -- never before that fence succeeds, and never
        if it did not (a worker fenced out during its own success
        publication must not touch this sub-resource; the winner that
        actually fenced it -- a later attempt, or recovery -- owns that
        transition instead). This ordering is the fix for PR95-H1: an
        adapter that also locks a sub-resource row (e.g. marking a plan
        `consumed`) must do so *after* Job -> Session, never before,
        keeping one global lock order shared with recovery and TX2
        failure publication (`on_execution_failure` below). Receives the
        same `resolved_resource_id` `execute()` recorded via
        `record_resolved_execution_resource` -- `None` for every adapter
        that predates this mechanism. Default: a no-op. If this raises,
        the exception propagates to TX1's own generic failure handling
        (rollback, then TX2 failure publication using this same
        `resolved_resource_id`) -- never partially applied."""
        return

    async def on_execution_failure(self, db: AsyncSession, resolved_resource_id: uuid.UUID | None) -> None:
        """Roadmap PR20E (design §14.4b). Called by the framework inside
        TX2, on TX2's own session, **after** `fenced_phase_failure` has
        already succeeded (fix round 2, §H1: the same Job -> Session ->
        resource lock order `on_execution_success` above uses -- a
        worker whose own failure publication was itself fenced out must
        never touch this sub-resource; whichever path actually won the
        fence owns that transition instead), immediately before TX2's
        own commit. Called whenever `execute()` raised, regardless of
        exception type -- not only `AdapterExecutionConflict` -- since
        fix round 2 also covers a failure occurring *after* `execute()`
        already returned successfully (still using the
        `resolved_resource_id` `execute()` recorded via
        `record_resolved_execution_resource`, never only a value carried
        by the exception itself). Receives only the bare primitive
        `resolved_resource_id` (never an ORM object -- TX1 has already
        rolled back, so any ORM-bound reference from `execute()` is
        detached/invalid). Default: a no-op -- every adapter that
        predates this mechanism, and any `None` resolved id, is
        unaffected. If this raises, TX2 itself aborts (the framework
        does not catch it) and the session/plan pair falls back to the
        existing generic fence-loss/recovery sweep -- never a new
        PR20-specific recovery mechanism."""
        return

    async def on_execution_recovery(self, db: AsyncSession, session_id: uuid.UUID) -> None:
        """Roadmap PR20E (design §14.4c). Called by `recover_session()`
        (`app.services.import_validation_service`), inside its existing
        recovery transaction, only when the recovered job's `job_type`
        was `"execute"` -- `dry_run`/`validate` recovery never needs this
        call. Gives an adapter with a persisted execution-time
        sub-resource (e.g. PR20's dry-run plan) a chance to reconcile it
        to a failed state using only the session id -- no exception, no
        captured primitive, since a hard worker crash (the case this hook
        exists for) produces neither. Default: a no-op. If this raises,
        the exception propagates uncaught and the caller's entire
        recovery transaction rolls back -- the stale job/session are left
        exactly as they were before this recovery attempt, available for
        a later recovery call to retry from scratch."""
        return


# §26/§10: production ships with no concrete adapter registered for any
# real dataset_type -- IMPORT_ADAPTER_NOT_REGISTERED (422) is therefore
# reachable for every real dataset_type until a future slice registers
# one. Tests register their own fake/test adapters here and must
# unregister them on teardown (see tests/conftest.py's
# `_import_adapter_registry` fixture) so no test adapter leaks into
# another test's assertions about this registry's default-empty state.
_ADAPTER_REGISTRY: dict[str, ImportAdapter] = {}


def register_adapter(adapter: ImportAdapter) -> None:
    _ADAPTER_REGISTRY[adapter.dataset_type] = adapter


def unregister_adapter(dataset_type: str) -> None:
    _ADAPTER_REGISTRY.pop(dataset_type, None)


def get_adapter(dataset_type: str) -> ImportAdapter | None:
    return _ADAPTER_REGISTRY.get(dataset_type)
