"""Roadmap PR22D -- Finding Review / Disposition API. Explicit Pydantic
request/response contracts for every endpoint (§25 of the task) -- ORM
models are never reused as API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import UUIDStr

RunStatus = Literal["pending", "running", "completed", "failed"]
FindingSeverity = Literal["high", "medium", "low"]
# OD-PR22-2's closed four-value vocabulary (app.models.legacy_reconciliation
# .RECONCILIATION_DISPOSITIONS) -- no fifth value, and specifically no
# `confirmed_pair` (§34 of the PR22C task; §3/§20/§21 of this one). A
# `Literal` here means an unknown or misspelled value is rejected by
# Pydantic itself as a standard 422, before any application code runs.
FindingDisposition = Literal["confirmed_valid", "confirmed_duplicate", "accepted_unresolved", "requires_correction"]


class RunListItem(BaseModel):
    """Review-relevant run metadata only -- never the raw ORM row (§6 of
    the task)."""

    id: UUIDStr
    status: RunStatus
    version: int
    rule_version: str
    snapshot_as_of: datetime
    created_by_user_id: UUIDStr
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    legacy_coverage_start: datetime
    legacy_coverage_end: datetime
    live_system_start: datetime
    summary_total_findings: int
    summary_high: int
    summary_medium: int
    summary_low: int
    # Read-only derived metadata only (a single `EXISTS`-style lookup,
    # batched across a whole page -- never per-row) -- exposing whether a
    # sign-off row already exists implements no sign-off behavior itself
    # (§6/§40 of the task: PR22E owns all of that).
    has_signoff: bool


class RunDetail(RunListItem):
    coverage_id: UUIDStr
    supersedes_run_id: UUIDStr | None
    # code -> count, via one GROUP BY query (§7/§23) -- "open" (SQL NULL)
    # is a real key here, never silently dropped.
    finding_counts_by_disposition: dict[str, int]


class FindingListItem(BaseModel):
    """Bounded list-row shape -- deliberately excludes `evidence` (§9 of
    the task: "avoid sending huge evidence structures in list
    responses")."""

    id: UUIDStr
    run_id: UUIDStr
    code: str
    severity: FindingSeverity
    equipment_id: UUIDStr | None
    rule_version: str
    disposition: FindingDisposition | None
    disposed_by_user_id: UUIDStr | None
    disposed_at: datetime | None
    disposition_note: str | None
    version: int
    created_at: datetime

    model_config = {"from_attributes": True}


class EquipmentSummary(BaseModel):
    """An explicit DTO, never the `Equipment` ORM row or its relationship
    internals (§10 of the task)."""

    id: UUIDStr
    asset_number: str
    equipment_name: str
    item_no: str | None
    bcm_code: str | None
    status: str

    model_config = {"from_attributes": True}


class LegacyEventRef(BaseModel):
    """The linked `LegacyEquipmentEvent` identifiers a finding's evidence
    references (§10) -- never the full event row, and never any raw
    workbook content."""

    id: UUIDStr
    event_type: str
    occurred_at: datetime
    legacy_source_row_key: str

    model_config = {"from_attributes": True}


class FindingDetail(FindingListItem):
    evidence: dict
    equipment: EquipmentSummary | None
    events: list[LegacyEventRef]


class FindingDispositionRequest(BaseModel):
    """PATCH request body. Deliberately excludes every machine-owned
    field (`code`/`severity`/`evidence`/`equipment_id`/`rule_version`/
    `run_id`/`created_at`) -- §17 of the task: no generic update schema,
    only these three fields may ever be submitted."""

    disposition: FindingDisposition
    expected_version: int = Field(ge=0)
    # Same bound as app.schemas.import_session.ImportSourceIn.notes --
    # this repository's existing free-text cap, not a new one. Rejected
    # (422) if exceeded, never silently truncated server-side (§18).
    disposition_note: str | None = Field(default=None, max_length=4000)


class SignOffRequest(BaseModel):
    """Roadmap PR22E §8 of the task. Deliberately the *only* field this
    request ever accepts -- `attestation_summary`/`rule_version`/
    `coverage timestamps`/finding counts/`signed_off_by_user_id`/
    `signed_off_at` are never accepted from the client; the backend
    constructs every attestation value from database truth inside the
    sign-off transaction (§20/§21 of the task)."""

    expected_version: int = Field(ge=0)


class SignOffDetail(BaseModel):
    """Roadmap PR22E §26 of the task. Explicit DTO -- never the ORM row
    or its internals."""

    id: UUIDStr
    run_id: UUIDStr
    signed_off_by_user_id: UUIDStr
    signed_off_at: datetime
    attestation_summary: dict
    run_version_at_signoff: int

    model_config = {"from_attributes": True}
