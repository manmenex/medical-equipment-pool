"""Roadmap PR21B/PR21C. Shared, dataset-agnostic result shapes -- neutral
between the Issue parser (PR21B) and the Receive parser (PR21C)
(§30/§31: "shared code must be neutral," no ISSUE/RECEIVE branch lives
in this module).

`LegacyIssueCandidate`/`LegacyIssueFinding` and
`LegacyReceiveCandidate`/`LegacyReceiveFinding` are deliberately kept as
separate dataclasses rather than merged into one shared
`LegacyHistoryCandidate`/`LegacyHistoryFinding` shape (PR21C fix task
§9/§10/§40: minimal churn preferred over aesthetic deduplication --
"leave separate dataclasses for clarity" is the explicitly acceptable
option, and this avoids any risk of an Issue-side regression from a
shared-type refactor)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SourceCoordinate:
    """One physical source position -- exactly the tuple
    `LegacyEquipmentEventSourceRef` persists per ref (§26): which sheet,
    which 1-based row. Never a business identity on its own (§24.2's
    Level 1, artifact-scoped only)."""

    sheet_name: str
    source_row_number: int


@dataclass(frozen=True)
class LegacyIssueCandidate:
    """§9's typed ISSUE candidate -- the sole output of this slice for a
    validated line-item row. Never persisted by this package (no
    `LegacyEquipmentEvent` INSERT anywhere in PR21B, §1/§40) -- a later,
    separately-authorized PR21D execution slice is the only place this
    shape is ever turned into a database write, using exactly the
    normalized identity captured here (§35: mappings are resolved once,
    at validation time, never invisibly re-resolved at execution time).

    Deliberately excludes any `หมายเหตุ`/notes content (OD-PR21-6, §21) --
    no field on this dataclass is ever populated from a notes cell."""

    event_type: str  # always "ISSUE" for this package
    legacy_source_row_key: str  # ลำดับ, from the line-item row
    legacy_order_reference: str  # เลขที่ใบส่ง (== the header's เลขที่ใบยืม)
    equipment_id: uuid.UUID
    occurred_at: datetime  # aware UTC
    legacy_ward_text: str | None
    resolved_ward_id: uuid.UUID | None
    legacy_bme_name: str | None
    migration_authority_id: uuid.UUID
    import_session_id: uuid.UUID
    import_source_id: uuid.UUID
    header_source_ref: SourceCoordinate
    line_source_ref: SourceCoordinate


@dataclass(frozen=True)
class LegacyIssueFinding:
    """One row-level validation finding, scoped to an exact source
    position (§26: sheet name + 1-based source row number, never merely
    a generic "row N" without saying which sheet -- header rows and line
    rows share no numbering space). `severity` is exactly `"error"` or
    `"warning"` (mirrors `app.services.import_adapter.FieldError`, kept
    as an independent dataclass here since this package's findings are
    always anchored to one of two sheets, not to a single adapter-wide
    row-number space)."""

    sheet_name: str
    source_row_number: int
    field: str | None
    error_code: str
    message: str
    severity: str = "error"


@dataclass(frozen=True)
class LegacyReceiveCandidate:
    """PR21C's typed RECEIVE candidate -- structurally identical to
    `LegacyIssueCandidate` (same fields, same semantics, only
    `event_type` differs), kept as its own dataclass rather than a
    shared base for minimal churn (see this module's docstring). Never
    persisted by this package (no `LegacyEquipmentEvent` INSERT anywhere
    in PR21C) -- a later, separately-authorized PR21D execution slice is
    the only place this shape is ever turned into a database write.

    Deliberately excludes any `หมายเหตุ`/notes content (OD-PR21-6) -- no
    field on this dataclass is ever populated from a notes cell."""

    event_type: str  # always "RECEIVE" for this package
    legacy_source_row_key: str  # ลำดับ, from the line-item row
    legacy_order_reference: str  # เลขที่ใบรับเครื่อง (== the header's เลขที่ใบคืน)
    equipment_id: uuid.UUID
    occurred_at: datetime  # aware UTC
    legacy_ward_text: str | None
    resolved_ward_id: uuid.UUID | None
    legacy_bme_name: str | None
    migration_authority_id: uuid.UUID
    import_session_id: uuid.UUID
    import_source_id: uuid.UUID
    header_source_ref: SourceCoordinate
    line_source_ref: SourceCoordinate


@dataclass(frozen=True)
class LegacyReceiveFinding:
    """RECEIVE-side counterpart to `LegacyIssueFinding` -- identical
    shape, kept separate for the same minimal-churn reason as
    `LegacyReceiveCandidate` above."""

    sheet_name: str
    source_row_number: int
    field: str | None
    error_code: str
    message: str
    severity: str = "error"
