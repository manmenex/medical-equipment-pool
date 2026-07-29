from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.reporting_time import Shift
from app.models.transaction import DispatchType, ReceiptOutcome, RoutineRound
from app.schemas.common import UUIDStr

# Roadmap PR9A: bounded, consistent with other free-text metadata fields in
# this schema module's neighborhood (e.g. EquipmentBase.equipment_name at
# 255) -- long enough for a genuine correction note, short enough to keep
# audit_logs.after_data (JSON/JSONB) from accepting unbounded input. No
# existing "reason"/"note" field in this codebase is currently length-bound
# at the schema layer (EquipmentStatusChange.reason, BorrowRequest.notes,
# ReturnRequest.notes are all unconstrained optional strings) -- this is the
# first, chosen deliberately per this task's explicit requirement rather
# than left open-ended, since a mandatory reason is exactly the kind of
# field an operator could paste unbounded text into.
WARD_CORRECTION_REASON_MAX_LENGTH = 500


class BorrowRequest(BaseModel):
    """Roadmap PR7b (docs/audits/04-consolidated-implementation-plan.md
    Part D PR7 entry; confirmed acceptance criteria in
    docs/audits/03-hospital-equipment-pool-workflow-audit.md §12):
    ``borrower_name``, ``due_at``, and ``quantity`` are deliberately absent
    -- no longer accepted or required (they were removed from the active
    dispatch write path; existing historical database values for all
    three are preserved and remain readable elsewhere, e.g.
    ``TransactionOut.borrower_name``/``quantity`` and
    ``app.services.report_service``'s export, which reads ``due_at``
    directly from the ORM row). ``ward_id`` and ``dispatch_type`` are now
    required for every new dispatch (same confirmed acceptance criteria);
    ``routine_round`` is required exactly when ``dispatch_type ==
    DispatchType.ROUTINE_ROUND`` and forbidden otherwise -- see the
    model_validator below.
    """

    # Equipment is always selected by internal UUID (See ADR-002) -- a QR
    # scan or BCM Code search resolves to one client-side, before this
    # request is made (See ADR-003, ADR-004). This endpoint does not
    # accept a raw QR/identifier value itself.
    equipment_id: str
    ward_id: str = Field(min_length=1)
    dispatch_type: DispatchType
    routine_round: RoutineRound | None = None
    department_id: str | None = None
    phone_number: str | None = None
    pickup_location_id: str | None = None
    dropoff_location_id: str | None = None
    notes: str | None = None

    # Codex PR20 review round 1, MAJOR 1: the default Pydantic/FastAPI
    # behavior used elsewhere in this codebase (silently ignore unrecognized
    # fields) let a caller still send borrower_name/due_at/quantity with no
    # error at all, which is not "removed from the contract" -- it's
    # silently accepted and discarded. BorrowRequest (only -- not a global
    # BaseModel change) now rejects any field it does not declare with a
    # 422, exactly like a missing required field, so all three genuinely
    # cannot be supplied.
    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _validate_routine_round(self) -> "BorrowRequest":
        # Confirmed acceptance criteria (docs/audits/04-consolidated-
        # implementation-plan.md §12 "Routine Dispatch"/"On-Demand
        # Dispatch"): a routine-round dispatch without a round is
        # rejected; an on-demand dispatch never carries a round value.
        if self.dispatch_type == DispatchType.ROUTINE_ROUND and self.routine_round is None:
            raise ValueError("routine_round is required when dispatch_type is 'routine_round'")
        if self.dispatch_type == DispatchType.ON_DEMAND and self.routine_round is not None:
            raise ValueError("routine_round must not be supplied when dispatch_type is 'on_demand'")
        return self


class ReturnRequest(BaseModel):
    """Roadmap PR8B (knowledge/adr/ADR-006-receipt-outcome-contract.md):
    the frozen, canonical receipt contract. ``receipt_outcome`` replaces
    the pre-PR8B four-value ``condition`` string entirely -- no
    compatibility alias is kept, since no external client is known to
    depend on the old field name (see the ADR's "Alternatives considered").
    A caller still sending ``condition`` gets a hard 422 (``extra:
    "forbid"``, the same BorrowRequest technique Roadmap PR7b's Codex
    review established), never a silently-ignored field. Backend alone
    maps this value to an `EquipmentStatus` (see
    app.services.borrow_service.RECEIPT_OUTCOME_TO_STATUS) -- the frontend
    must never submit a lifecycle state (`AVAILABLE_AT_POOL`/
    `UNAVAILABLE_DEFECTIVE`) directly.
    """

    receipt_outcome: ReceiptOutcome
    notes: str | None = None

    model_config = {"extra": "forbid"}


class WardCorrectionRequest(BaseModel):
    """Roadmap PR9A (docs/audits/03-hospital-equipment-pool-workflow-audit.md
    §7 "Ward Recording Rules": "Add a narrow, role-gated ... fully-audited
    'Correct Destination Ward' action -- distinct from any general edit
    capability, writing a clear before/after audit entry every time it's
    used"; §10's permission matrix requires "(with mandatory audit note)").
    Exactly two fields, matching that scope precisely -- this is not a
    generic transaction PATCH (see docs/DECISION_LOG.md "Roadmap PR9A"):

    - ``ward_id``: the corrected destination ward. A native ``UUID`` field
      (not ``str``) so an invalid identifier fails Pydantic's own
      validation with a standard 422 -- no bespoke parsing/normalization of
      a malformed value is performed anywhere in this request's handling.
    - ``reason``: the mandatory correction note the audit trail requires.
      Trimmed before length/blank validation (a value that is only
      whitespace must be rejected the same as an empty one, not accepted
      because it has nonzero raw length), bounded at
      ``WARD_CORRECTION_REASON_MAX_LENGTH``.

    ``extra: "forbid"`` (the same BorrowRequest/ReturnRequest technique
    Roadmap PR7b/PR8B established) -- a caller sending any other field gets
    a hard 422, never a silently-ignored one.
    """

    ward_id: UUID
    reason: str = Field(min_length=1, max_length=WARD_CORRECTION_REASON_MAX_LENGTH)

    model_config = {"extra": "forbid"}

    @field_validator("reason", mode="before")
    @classmethod
    def _trim_reason(cls, value: object) -> object:
        # mode="before" runs ahead of Field's min_length/max_length checks,
        # so a whitespace-only submission (e.g. "   ") is trimmed down to ""
        # first and then correctly rejected by min_length=1 -- never
        # accepted just because its raw, untrimmed length was nonzero.
        if isinstance(value, str):
            return value.strip()
        return value


class EquipmentSummary(BaseModel):
    id: UUIDStr
    asset_number: str
    equipment_name: str
    status: str

    model_config = {"from_attributes": True}


class TransactionOut(BaseModel):
    id: UUIDStr
    transaction_no: str
    equipment: EquipmentSummary
    quantity: int
    borrowed_at: datetime
    # Roadmap PR7b: due_at is deliberately absent -- removed from the
    # active request/response contract entirely (ADR-005 decision 3 already
    # retired the due-date/overdue workflow). The column and every existing
    # value are unchanged in the database; historical due_at remains
    # queryable/exportable via app.services.report_service, which reads it
    # directly from the ORM row, not through this response schema.
    returned_at: datetime | None
    # Nullable going forward (Roadmap PR7b) -- a dispatch created before
    # this change always has a value; one created after it never does.
    # Preserved and shown here as read-only history either way.
    borrower_name: str | None
    ward_id: UUIDStr | None
    dispatch_type: DispatchType | None
    routine_round: RoutineRound | None
    phone_number: str | None
    # Roadmap PR8B: renamed from condition_on_return to the frozen
    # receipt_outcome business term. Codex review round 1, finding 2:
    # since the request contract is strictly binary, the response field of
    # the same name must be strictly binary too -- `ReceiptOutcome | None`,
    # never one of the pre-PR8B legacy strings. `None` both for a
    # transaction not yet received and for one received before this
    # contract existed (BorrowTransaction.receipt_outcome's docstring).
    receipt_outcome: ReceiptOutcome | None
    # A pre-PR8B legacy value (`available`/`pm`/`calibration`/`repair`),
    # preserved verbatim and read-only, exactly as it was recorded --
    # never translated into the new domain. Always `None` for a
    # transaction received under the current contract, and always `None`
    # for one not yet received -- mutually exclusive with `receipt_outcome`
    # above (BorrowTransaction.legacy_condition_on_return's docstring).
    legacy_condition_on_return: str | None
    status: str
    notes: str | None
    # Roadmap PR16 Slice 2 (docs/design/PR16_REPORTING_FOUNDATION_PLAN.md
    # §9) -- read-only, computed, never accepted as request input.
    # dispatch_* is always present (every transaction has a `borrowed_at`);
    # receipt_* is `None` until the transaction is received, mirroring
    # `receipt_outcome`'s existing None-until-received rule
    # (BorrowTransaction.dispatch_business_date/.../.receipt_shift's
    # docstrings).
    dispatch_business_date: date
    dispatch_shift: Shift
    receipt_business_date: date | None
    receipt_shift: Shift | None

    model_config = {"from_attributes": True}
