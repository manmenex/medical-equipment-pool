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
