"""Roadmap PR22C (§10, §29) -- the internal, strongly typed shapes rule
modules exchange with the engine. Rules never touch the ORM session or
instantiate `LegacyReconciliationFinding` rows directly (§9): each rule
is a pure function over an immutable `ReconciliationContext`
(`app.services.reconciliation.context`) that returns a tuple of
`FindingCandidate` objects; `app.services.reconciliation.persistence`
is the sole place that turns candidates into ORM rows, centrally, after
every rule has run (§25/§26).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class FindingCandidate:
    """One deterministic candidate finding produced by a rule module.

    `evidence` must be structured, bounded, deterministic, and JSON
    serializable (§10, §29) -- never a dump of an ORM object or a raw
    source-row blob. `legacy_event_ids` is the exact, deterministically
    ordered set of `LegacyEquipmentEvent` ids this finding's evidence
    structurally references (§14/§26) -- persisted as real junction rows
    (`LegacyReconciliationFindingEvent`), never folded into `evidence`
    itself. `sort_key` is a fully deterministic tuple used to order
    candidates before persistence (§11) -- never Python set/dict
    iteration order, DB natural row order, or a freshly generated UUID.
    """

    code: str
    severity: str
    evidence: dict
    sort_key: tuple
    equipment_id: uuid.UUID | None = None
    legacy_event_ids: tuple[uuid.UUID, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.severity not in ("high", "medium", "low"):
            raise ValueError(f"FindingCandidate.severity must be one of high/medium/low, got {self.severity!r}")
        if len(self.code) > 50:
            raise ValueError(f"FindingCandidate.code must fit VARCHAR(50), got {len(self.code)} chars: {self.code!r}")


@dataclass(frozen=True)
class LegacyEventSnapshot:
    """Read-only, deterministic snapshot of one `LegacyEquipmentEvent`
    row -- rules read this, never the live ORM row, so a rule can never
    accidentally mutate permanent historical evidence (§2/§35)."""

    id: uuid.UUID
    equipment_id: uuid.UUID
    event_type: str
    occurred_at: "object"
    legacy_source_row_key: str
    legacy_order_reference: str | None
    legacy_ward_text: str | None
    resolved_ward_id: uuid.UUID | None
    legacy_bme_name: str | None
    migration_authority_id: uuid.UUID
    import_session_id: uuid.UUID
    import_source_id: uuid.UUID


@dataclass(frozen=True)
class SourceRefSnapshot:
    """Read-only snapshot of one `LegacyEquipmentEventSourceRef` row."""

    id: uuid.UUID
    legacy_equipment_event_id: uuid.UUID
    sheet_name: str
    source_row_number: int
    source_checksum: str


@dataclass(frozen=True)
class TransactionSnapshot:
    """Read-only snapshot of one `BorrowTransaction` row -- the modern
    (post-cutover) side of the unified history projection (§19)."""

    id: uuid.UUID
    equipment_id: uuid.UUID
    status: str
    borrowed_at: "object"
    returned_at: "object | None"
    ward_id: uuid.UUID | None


@dataclass(frozen=True)
class EquipmentSnapshot:
    """Read-only snapshot of one `Equipment` row -- never mutated by
    this package (§2/§35)."""

    id: uuid.UUID
    status: str
    asset_number: str
    bcm_code: str | None
    item_no: str | None


@dataclass(frozen=True)
class HistoryProjectionEvent:
    """Roadmap PR22C §19/§47 -- one normalized event in the unified
    legacy + modern history projection. Read/query projection only --
    never persisted as another history table. `source_kind` distinguishes
    provenance; `legacy_event_id`/`modern_transaction_id` are mutually
    exclusive, never both set, and exactly one is set."""

    source_kind: str  # "legacy_issue" | "legacy_receive" | "modern_issue" | "modern_receive"
    equipment_id: uuid.UUID
    event_kind: str  # "ISSUE" | "RECEIVE"
    occurred_at: "object"
    ward_id: uuid.UUID | None
    legacy_event_id: uuid.UUID | None
    modern_transaction_id: uuid.UUID | None
    authority_id: uuid.UUID | None

    @property
    def sort_key(self) -> tuple:
        """Deterministic total order: by instant, then a fixed source-kind
        priority (legacy before modern on an exact tie, an arbitrary but
        stable rule), then by the underlying row id -- never left to
        Python iteration order or DB natural order (§11)."""
        source_priority = 0 if self.source_kind.startswith("legacy_") else 1
        row_id = self.legacy_event_id or self.modern_transaction_id
        return (self.occurred_at, source_priority, str(row_id))
