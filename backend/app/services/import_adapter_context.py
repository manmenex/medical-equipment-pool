"""Adapter Invocation Context -- session/source identity for
`plan_dry_run`/`execute`.

Roadmap PR20A (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md §6.4,
architecture-approved via the merged Design PR #89). `import_execution_
service.run_dry_run` calls exactly `await adapter.plan_dry_run(ro_db)`,
and `run_execute` calls exactly `await adapter.execute(db)` -- neither
passes `import_session_id`, `import_source_id`, or any other identity
parameter (confirmed by reading the actual merged call sites). An adapter
that needs its own session/source identity to run `plan_dry_run`/
`execute` (e.g. to load its own persisted dry-run plan by session id, a
later PR20D/PR20E concern) cannot get it from either method's own merged
ABC signature, and must never resolve it by querying for "whichever job
is currently running" -- unsafe under concurrent sessions of the same
dataset_type, and exactly the "adapter reconstructing source identity by
querying arbitrary tables on its own" anti-pattern this module exists to
rule out.

This is a small, additive, backward-compatible extension to the PR19A
service layer: `import_validation_service`/`import_execution_service`
never change signature or observable behavior for any adapter that
doesn't call `get_adapter_invocation_context()` -- no other adapter
exists yet, so nothing in this foundation actually depends on this
mechanism being populated with anything beyond `None`/empty defaults."""

from __future__ import annotations

import contextvars
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from app.services.import_source_reader import VerifiedSourceContent


@dataclass(frozen=True)
class AdapterInvocationContext:
    """Immutable. Set by the framework immediately before calling
    `adapter.plan_dry_run`/`adapter.execute`, read by the concrete
    adapter's own implementation of those methods via
    `get_adapter_invocation_context()` -- never passed as a positional/
    keyword argument, so `ImportAdapter`'s existing merged ABC method
    signatures are not modified."""

    import_session_id: uuid.UUID
    import_source_id: uuid.UUID
    dataset_type: str
    source_checksum: str
    source_fingerprint: str
    ruleset_version: str
    # Populated only for `plan_dry_run` -- the framework calls
    # `ImportSourceReader.open_verified(...)` itself on the read-only
    # session and places the result here *before* invoking
    # `plan_dry_run`, mirroring how `run_validation` already passes
    # verified content to `parse()` as a direct argument. Always `None`
    # for `execute`, which never re-reads or re-parses the source.
    verified_source_content: VerifiedSourceContent | None
    # Populated only for `plan_dry_run` -- the exact `ImportJob.id` the
    # framework has just admitted for *this* dry-run attempt. `None` for
    # `execute`.
    dry_run_job_id: uuid.UUID | None
    # Populated only for `plan_dry_run` -- the exact `ImportJob.id` of the
    # session's currently accepted validation snapshot
    # (`ImportSession.current_validation_job_id`, existing PR19A field).
    # `None` for `execute`.
    accepted_validation_job_id: uuid.UUID | None
    # Roadmap PR20D (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md §26):
    # the acting user, for audit-event attribution only -- both
    # `run_dry_run`/`run_execute` already receive this as their own
    # `actor_id` parameter, so no new identity resolution is introduced.
    # Read by `EquipmentMasterAdapter.persist_dry_run_plan` to attribute
    # the `import_dry_run_plan_created` audit event; every other adapter
    # method that doesn't call `get_adapter_invocation_context()` is
    # unaffected.
    actor_user_id: uuid.UUID | None


_adapter_invocation_context: contextvars.ContextVar[AdapterInvocationContext | None] = contextvars.ContextVar(
    "_adapter_invocation_context", default=None
)


def get_adapter_invocation_context() -> AdapterInvocationContext:
    ctx = _adapter_invocation_context.get()
    if ctx is None:
        raise RuntimeError(
            "No AdapterInvocationContext is set -- plan_dry_run/execute must only be called from within "
            "the framework's own context-setting wrapper (see app.services.import_adapter_context."
            "adapter_invocation_context)."
        )
    return ctx


# Roadmap PR20E fix round 2 (PR #95 review, §H2). `AdapterExecutionConflict.
# resolved_resource_id` (app.services.import_adapter) only ever reaches the
# framework when `execute()` itself *raises* -- but a genuine conflict can
# also surface *after* `execute()` has already returned successfully (a
# later failure in the framework's own fenced-completion/audit/commit work,
# still inside the same TX1). Without a way to learn the resolved
# sub-resource id in that case too, the framework's TX2 failure-publication
# path has nothing to pass to `on_execution_failure`, and a session can be
# published `failed` while its DryRunPlan stays `active` forever.
#
# `record_resolved_execution_resource`/`get_resolved_execution_resource`
# close that gap: an adapter's own `execute()` calls the former immediately
# upon resolving its persisted sub-resource (e.g. the confirmed DryRunPlan),
# *before* attempting any mutation -- so the value is available
# unconditionally, on both the success and failure return paths, never only
# via an exception. `adapter_invocation_context` (below) resets this to
# `None` on every entry, so a value recorded during one `execute()`
# invocation can never leak into a later, unrelated one on the same
# `asyncio` task (e.g. a test harness calling `execute()` directly, more
# than once, within a single coroutine).
_resolved_execution_resource: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar(
    "_resolved_execution_resource", default=None
)


def record_resolved_execution_resource(resource_id: uuid.UUID) -> None:
    """Called by an adapter's own `execute()` (never by the framework)
    immediately after resolving its persisted sub-resource, before any
    mutation is attempted. An opaque, adapter-defined primitive -- never
    an ORM object, exactly the same contract `AdapterExecutionConflict.
    resolved_resource_id` already established."""
    _resolved_execution_resource.set(resource_id)


def get_resolved_execution_resource() -> uuid.UUID | None:
    """The framework's own read side. `None` means either the adapter
    never called `record_resolved_execution_resource` (every adapter
    that predates this mechanism), or `execute()` failed before
    resolving anything."""
    return _resolved_execution_resource.get()


@contextmanager
def adapter_invocation_context(context: AdapterInvocationContext) -> Iterator[None]:
    """`contextvars.Token`-based set/reset (Python's standard, task-safe
    pattern) -- each `asyncio` task gets its own copy of the context, so
    two concurrent sessions' dry-run/execute calls never observe each
    other's context, unlike a plain module-level global. The framework
    (`import_execution_service.run_dry_run`/`run_execute`) wraps exactly
    the `adapter.plan_dry_run(...)`/`adapter.execute(...)` call in this
    context manager -- nothing else. Also resets
    `_resolved_execution_resource` to `None` on entry, so each
    invocation starts with a clean slate regardless of what a prior
    invocation on the same task may have recorded."""
    token = _adapter_invocation_context.set(context)
    resource_token = _resolved_execution_resource.set(None)
    try:
        yield
    finally:
        _adapter_invocation_context.reset(token)
        _resolved_execution_resource.reset(resource_token)
