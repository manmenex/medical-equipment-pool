from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.transaction import DispatchType, RoutineRound
from app.schemas.common import UUIDStr


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
    # Roadmap PR6 / owner-confirmed cleaning retirement: "cleaning" is
    # deliberately absent from this contract -- cleaning happens as part
    # of collecting/receiving equipment (AGENTS.md), not a distinct return
    # outcome. Passing it is rejected the same as any other unrecognized
    # condition (see app.services.borrow_service.RETURN_CONDITION_TO_STATUS
    # / return_equipment), never silently accepted. This field is pre-PR8:
    # the atomic single-operation, binary usable/defective receipt contract
    # is not implemented here.
    condition: str = Field(description="available|pm|calibration|repair")
    notes: str | None = None


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
    condition_on_return: str | None
    status: str
    notes: str | None

    model_config = {"from_attributes": True}
