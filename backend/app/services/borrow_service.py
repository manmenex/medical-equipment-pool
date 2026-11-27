import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Request
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AUDIT_ACTION_WARD_CORRECTION, AUDIT_ENTITY_BORROW_TRANSACTION, record_audit_event
from app.core.db_errors import IntegrityViolationKind, classify_integrity_error
from app.core.exceptions import (
    CorrectionConflictError,
    CorrectionNotLatestError,
    CorrectionNotPermittedError,
    CorrectionStateChangedError,
    SwitchActionNotAvailableError,
    UndoWindowExpiredError,
    DispatchStatusWarningError,
    DispatchWarningStaleError,
    EquipmentStatusChangedError,
    TransactionClosedByRedispatchError,
    EquipmentNotAvailableError,
    EquipmentReturnedToOwnerError,
    EquipmentNotFoundError,
    InvalidInputError,
    ReceiptRaceLostError,
    TransactionAlreadyReturnedError,
    TransactionNotFoundError,
    TransactionVoidedError,
    WardCorrectionConflictError,
    WardCorrectionNoOpError,
)
from app.core.redis import cache_delete_prefix
from app.core.references import ensure_referenced_row_exists
from app.core.reporting_time import business_date_and_shift
from app.core import hn_crypto
from app.crud import audit as audit_crud
from app.crud import client_operation as client_op_crud
from app.crud import cuff as cuff_crud
from app.crud import equipment as equipment_crud
from app.crud import transaction as transaction_crud
from app.models.equipment import EquipmentStatus
from app.models.export import EVENT_TYPE_DISPATCH, EVENT_TYPE_RECEIPT
from app.models.master_data import Ward
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, Role
from app.models.transaction import (
    CLOSE_REASON_REDISPATCH,
    BorrowTransaction,
    DispatchType,
    ReceiptOutcome,
    RoutineRound,
    TransactionStatus,
)
from app.schemas.checklist import Checks, CuffCounts, CryoCuffChecks, StandardChecks
from app.services import checklist_service, cuff_service, export_service
from app.utils.parsing import parse_uuid

# Roadmap PR8B (knowledge/adr/ADR-006-receipt-outcome-contract.md): the
# frozen binary receipt contract. Replaces the pre-PR8B four-value
# RETURN_CONDITION_TO_STATUS dict (`available`/`pm`/`calibration`/
# `repair`) -- a `ReceiptOutcome` is validated by app.schemas.transaction.
# ReturnRequest before this service ever runs, so this mapping is total
# over the enum's members; there is no "unknown outcome" branch to guard
# here anymore (see return_equipment below). Cleaning remains deliberately
# absent (Roadmap PR6 / owner-confirmed cleaning retirement, AGENTS.md): a
# usable receipt already becomes AVAILABLE_AT_POOL directly, and cleaning
# is never a distinct receipt outcome.
RECEIPT_OUTCOME_TO_STATUS = {
    ReceiptOutcome.USABLE: EquipmentStatus.AVAILABLE_AT_POOL,
    ReceiptOutcome.DEFECTIVE: EquipmentStatus.UNAVAILABLE_DEFECTIVE,
}


# Roadmap PR31 (Owner Governance 2026-11-25 D8): warning kinds returned by
# assess_dispatch() and surfaced in DispatchStatusWarningError.details.
WARNING_ALREADY_DISPATCHED = "already_dispatched"
WARNING_DEFECTIVE = "defective"
WARNING_DECOMMISSIONED = "decommissioned"
# Roadmap PR33 (D14): demo/loan equipment returned to its owner; blocked like
# decommissioned but with its own code (EQUIPMENT_RETURNED_TO_OWNER).
WARNING_RETURNED_TO_OWNER = "returned_to_owner"


@dataclass
class DispatchAssessment:
    """What dispatching this equipment right now would mean (D8). ``warning``
    is None for ``available_at_pool`` (plain dispatch), a warning kind that
    needs operator confirmation, or WARNING_DECOMMISSIONED (blocked, never
    confirmable)."""

    equipment: "object"
    warning: str | None
    open_transaction: BorrowTransaction | None = None
    ward_name: str | None = None

    @property
    def blocked(self) -> bool:
        return self.warning in (WARNING_DECOMMISSIONED, WARNING_RETURNED_TO_OWNER)

    @property
    def requires_acknowledgement(self) -> bool:
        return self.warning in (WARNING_ALREADY_DISPATCHED, WARNING_DEFECTIVE)

    def details(self) -> dict:
        tx = self.open_transaction
        return {
            "warning": self.warning,
            "equipment_status": self.equipment.status.value,
            "current_ward_id": str(tx.ward_id) if tx is not None and tx.ward_id else None,
            "current_ward_name": self.ward_name,
            "dispatched_at": tx.borrowed_at.isoformat() if tx is not None else None,
            "open_transaction_id": str(tx.id) if tx is not None else None,
            "open_transaction_no": tx.transaction_no if tx is not None else None,
        }

    def message(self) -> str:
        if self.warning == WARNING_ALREADY_DISPATCHED:
            return "Equipment is already dispatched and its receipt has not been recorded"
        if self.warning == WARNING_DEFECTIVE:
            return "Equipment is marked defective"
        return f"Equipment is currently in status '{self.equipment.status.value}'"


async def assess_dispatch(db: AsyncSession, equipment) -> DispatchAssessment:
    """Shared by borrow() and the GET /equipment/{id}/dispatch-check
    pre-check so the scan-time warning and the dispatch guard cannot drift.
    Exact-equality dispatch: every status is named, never a negative check."""
    if getattr(equipment, "returned_to_owner_at", None) is not None:
        return DispatchAssessment(equipment, WARNING_RETURNED_TO_OWNER)
    status = equipment.status
    if status == EquipmentStatus.AVAILABLE_AT_POOL:
        return DispatchAssessment(equipment, None)
    if status == EquipmentStatus.UNAVAILABLE_DEFECTIVE:
        return DispatchAssessment(equipment, WARNING_DEFECTIVE)
    if status == EquipmentStatus.ISSUED_TO_WARD:
        open_tx = await transaction_crud.get_open_transaction_for_equipment(db, equipment.id)
        ward_name = None
        if open_tx is not None and open_tx.ward_id is not None:
            ward = await db.get(Ward, open_tx.ward_id)
            ward_name = ward.name if ward is not None else None
        return DispatchAssessment(equipment, WARNING_ALREADY_DISPATCHED, open_tx, ward_name)
    return DispatchAssessment(equipment, WARNING_DECOMMISSIONED)


async def borrow(
    db: AsyncSession,
    *,
    equipment_id: str,
    borrower_user_id: uuid.UUID | None,
    ward_id: str,
    dispatch_type: DispatchType | None,
    routine_round: RoutineRound | None,
    department_id: str | None,
    phone_number: str | None,
    pickup_location_id: str | None,
    dropoff_location_id: str | None,
    notes: str | None,
    ip_address: str | None,
    user_agent: str | None,
    actor_user_id: uuid.UUID | None = None,
    client_op: client_op_crud.ClientOpContext | None = None,
    borrowed_at: datetime | None = None,
    acknowledge_status_warning: bool = False,
    expected_open_transaction_id: str | None = None,
    ward_contact_name: str | None = None,
    dispatch_checks: StandardChecks | CryoCuffChecks | None = None,
    expected_status: EquipmentStatus | None = None,
    hn: str | None = None,
    _commit: bool = True,
) -> BorrowTransaction:
    # D28: ``_commit=False`` is for the correction services only (change
    # device / switch action), which must make the void and the corrected
    # event one atomic unit and commit once themselves.
    # Roadmap PR25E slice B2b: ``borrowed_at`` is business time and is passed
    # only by the sync layer after the section 11 guards; online callers omit
    # it and keep the server clock.
    # Roadmap PR25E slice B2 (docs/design/PR25D_OFFLINE_OPERATION_PLAN.md
    # sections 6.3, 8.3): ``borrower_user_id`` is the *recorded operator*;
    # ``actor_user_id`` is who performed the write (audit actor and
    # equipment status-history ``changed_by_user_id``) and defaults to the
    # operator, so every online call is unchanged. ``client_op`` is passed
    # only by the sync layer: the dispatch then uses ``client_op.op_id`` as
    # the transaction id and the ledger row is written (flush only) before
    # the export event and the single commit below.
    actor_user_id = actor_user_id if actor_user_id is not None else borrower_user_id
    # Equipment selection is always by internal UUID (See ADR-002): a QR
    # scan resolves to one via POST /equipment/resolve-qr first (exact
    # Item No match, See ADR-004), and manual selection resolves one via a
    # BCM Code suggestion (See ADR-003) -- this endpoint itself never
    # accepts a raw scanned/typed identifier.
    equipment = await equipment_crud.get_by_id(db, parse_uuid(equipment_id, "equipment_id"))

    if equipment is None:
        raise EquipmentNotFoundError("Equipment not found")

    # Roadmap PR31 (D8) replaces the PR6 `status == AVAILABLE_AT_POOL` gate:
    # dispatch is no longer blocked by equipment status. Every status is
    # named explicitly (assess_dispatch); DECOMMISSIONED is still rejected,
    # and an already-dispatched or defective item needs the operator's
    # explicit acknowledgement (409 DISPATCH_STATUS_WARNING + details).
    # Roadmap PR28 (D4/D10): the checklist shape must match the equipment's
    # category-driven kind; rejected before any write.
    checklist_kind = await checklist_service.kind_for_equipment(db, equipment)
    checklist_service.ensure_kind_matches(dispatch_checks, checklist_kind)

    # Roadmap PR29 (D1): encrypt BEFORE any write; a missing key rejects the
    # dispatch with HN_UNAVAILABLE and nothing is stored. The plaintext never
    # leaves this function (not in the audit row, logs or the return value).
    hn_ciphertext = hn_crypto.encrypt_hn(hn) if hn else None

    assessment = await assess_dispatch(db, equipment)
    if assessment.blocked:
        if assessment.warning == WARNING_RETURNED_TO_OWNER:
            raise EquipmentReturnedToOwnerError("Equipment was returned to its owner and cannot be dispatched")
        raise EquipmentNotAvailableError(assessment.message())
    if expected_status is not None and equipment.status != expected_status:
        # Roadmap PR27 review gap: a confirmation given for one status must
        # not apply after the status changed (e.g. defective -> available).
        raise DispatchWarningStaleError(
            "The equipment's status changed since it was shown. Refresh and confirm again.",
            details={**assessment.details(), "expected_status": expected_status.value},
        )
    if assessment.requires_acknowledgement and not acknowledge_status_warning:
        raise DispatchStatusWarningError(assessment.message(), details=assessment.details())
    redispatched_tx = assessment.open_transaction
    if expected_open_transaction_id is not None and (
        redispatched_tx is None or str(redispatched_tx.id) != expected_open_transaction_id
    ):
        raise DispatchWarningStaleError(
            "The equipment's dispatch state changed since the warning was shown. Refresh and confirm again.",
            details=assessment.details(),
        )
    if redispatched_tx is not None and borrowed_at is not None:
        # The new dispatch never predates the one it closes (offline business
        # time can be older than the transaction recorded meanwhile).
        prev = redispatched_tx.borrowed_at
        prev = prev.replace(tzinfo=timezone.utc) if prev.tzinfo is None else prev
        at = borrowed_at.replace(tzinfo=timezone.utc) if borrowed_at.tzinfo is None else borrowed_at
        if at < prev:
            borrowed_at = prev
    dispatched_while_defective = assessment.warning == WARNING_DEFECTIVE
    previous_status = equipment.status

    # Codex PR20 review round 1, MAJOR 3: ward_id is required (Roadmap
    # PR7b), so an invalid reference here is a genuine, common client input
    # error, not the rare concurrent-dispatch race the IntegrityError
    # handler below exists for -- it must not surface as "Equipment was
    # just borrowed by someone else". Validated proactively, the same
    # pattern app.api.v1.equipment/master_data already use for their own
    # foreign-key fields (see app.core.references), so it is a 400
    # InvalidInputError (code INVALID_INPUT) on both SQLite (which does not
    # enforce FK constraints) and PostgreSQL alike, and the IntegrityError
    # handler below is only ever reached for a genuine unique-index
    # collision.
    ward_uuid = parse_uuid(ward_id, "ward_id")
    await ensure_referenced_row_exists(db, Ward, ward_uuid, field_name="ward_id")

    transaction_no = await transaction_crud.generate_transaction_no(db)

    # Roadmap PR7b: ward_id and dispatch_type are required for every new
    # dispatch (docs/audits/04-consolidated-implementation-plan.md's
    # confirmed acceptance criteria); routine_round/on-demand consistency
    # is already validated by app.schemas.transaction.BorrowRequest before
    # this service is ever called. quantity/due_at/borrower_name are no
    # longer accepted here at all -- quantity and borrower_name rely on
    # their column defaults (1 and NULL respectively); due_at is never set
    # by a new dispatch (ADR-005 decision 3).
    if redispatched_tx is not None:
        # D8 (a): close the previous open transaction in the SAME database
        # transaction as the new dispatch below. The conditional UPDATE
        # (WHERE status = 'open', decided by rowcount) is the concurrency
        # guard: of two concurrent re-dispatches (or a re-dispatch racing a
        # receipt) exactly one closes it; the loser writes nothing.
        closed = await transaction_crud.close_for_redispatch(db, redispatched_tx)
        if not closed:
            await db.rollback()
            raise EquipmentNotAvailableError(
                "Equipment was just received or dispatched by someone else. Refresh to see the current state."
            )

    try:
        tx = await transaction_crud.create(
            db,
            id=(
                (client_op.transaction_id_override or client_op.op_id)
                if client_op is not None
                else None
            ),
            borrowed_at=borrowed_at,
            data={
                "transaction_no": transaction_no,
                "equipment_id": equipment.id,
                "borrower_user_id": borrower_user_id,
                "ward_id": ward_uuid,
                "dispatch_type": dispatch_type,
                "routine_round": routine_round,
                "department_id": parse_uuid(department_id, "department_id"),
                "phone_number": phone_number,
                "pickup_location_id": parse_uuid(pickup_location_id, "pickup_location_id"),
                "dropoff_location_id": parse_uuid(dropoff_location_id, "dropoff_location_id"),
                "notes": notes,
                "dispatched_while_defective": dispatched_while_defective,
                "dispatch_contact_name": ward_contact_name,
                "checklist_kind": checklist_kind,
                "hn_ciphertext": hn_ciphertext,
                "has_hn": hn_ciphertext is not None,
                # D28 restore source: see BorrowTransaction.prior_equipment_status.
                "prior_equipment_status": previous_status.value,
                "closed_by_redispatch_transaction_id": redispatched_tx.id if redispatched_tx is not None else None,
                # Omitted (None) stays SQL NULL = "not recorded".
                **({"dispatch_checks": dispatch_checks.model_dump(mode="json")} if dispatch_checks is not None else {}),
            },
        )
    except IntegrityError as exc:
        await db.rollback()
        # Codex PR20 review round 1, MAJOR 3: only a genuine unique-index
        # collision (idx_tx_one_active_borrow -- two concurrent dispatches
        # of the same equipment) maps to the existing concurrency response.
        # ward_id is already validated above, so a foreign-key violation
        # reaching here would mean the ward was deleted in the narrow
        # window between that check and this flush -- still a bad
        # reference, not an equipment conflict -- and any other
        # classification is treated the same way: never silently
        # mislabeled as "Equipment was just borrowed by someone else".
        if classify_integrity_error(exc) is IntegrityViolationKind.UNIQUE:
            raise EquipmentNotAvailableError("Equipment was just borrowed by someone else") from exc
        raise InvalidInputError("This dispatch references data that is no longer valid.") from exc

    try:
        await equipment_crud.change_status_for_dispatch_receipt(
            db,
            equipment,
            new_status=EquipmentStatus.ISSUED_TO_WARD,
            changed_by_user_id=actor_user_id,
            reason="Re-dispatched" if redispatched_tx is not None else "Dispatched",
        )
    except EquipmentStatusChangedError:
        # Includes the close/insert above: all or nothing.
        await db.rollback()
        raise
    audit_after = {"transaction_no": tx.transaction_no, "equipment_id": str(equipment.id)}
    if dispatch_checks is not None:
        audit_after["checklist_kind"] = checklist_kind
    if hn_ciphertext is not None:
        audit_after["has_hn"] = True  # never the value
    if dispatched_while_defective:
        audit_after["dispatched_while_defective"] = True
        audit_after["previous_equipment_status"] = previous_status.value
    if redispatched_tx is not None:
        audit_after["redispatch_closed_transaction_id"] = str(redispatched_tx.id)
        await audit_crud.create(
            db,
            user_id=actor_user_id,
            action="redispatch_close",
            entity_type="borrow_transaction",
            entity_id=redispatched_tx.id,
            before_data={"status": TransactionStatus.OPEN.value},
            after_data={
                "status": TransactionStatus.CLOSED.value,
                "close_reason": CLOSE_REASON_REDISPATCH,
                "closed_by_transaction_id": str(tx.id),
                "closed_by_transaction_no": tx.transaction_no,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )
    if client_op is not None:
        audit_after.update(client_op.audit_fields())
    await audit_crud.create(
        db,
        user_id=actor_user_id,
        action="borrow",
        entity_type="borrow_transaction",
        entity_id=tx.id,
        after_data=audit_after,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    if isinstance(dispatch_checks, CryoCuffChecks) and dispatch_checks.cuffs.total() > 0:
        # Roadmap PR28 (D11): cuffs issued with the device, attributed to this
        # transaction (and so its ward) until returned.
        await cuff_crud.create_issued(db, transaction_id=tx.id, counts=dispatch_checks.cuffs)
        await cuff_service.audit_issue(
            db,
            actor_user_id=actor_user_id,
            transaction_id=tx.id,
            counts=dispatch_checks.cuffs,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    if client_op is not None:
        # Section 6.3 step 2: ledger row after the business writes and audit,
        # BEFORE record_event (which must stay the last write).
        await client_op_crud.write_applied(db, client_op, transaction_id=tx.id, occurred_at=tx.borrowed_at)
    # Roadmap PR25B: must stay the LAST write before commit -- it takes the
    # export counter's row lock, which is what makes the export cursor
    # follow commit order (see app.services.export_service).
    await export_service.record_event(
        db, transaction_id=tx.id, event_type=EVENT_TYPE_DISPATCH, event_at=tx.borrowed_at
    )
    if not _commit:
        return tx
    await db.commit()
    await cache_delete_prefix("equipment:search:")
    await cache_delete_prefix("dashboard:")
    return tx


async def return_equipment(
    db: AsyncSession,
    *,
    transaction_id: uuid.UUID,
    receipt_outcome: ReceiptOutcome,
    notes: str | None,
    received_by_user_id: uuid.UUID | None,
    ip_address: str | None,
    user_agent: str | None,
    actor_user_id: uuid.UUID | None = None,
    client_op: client_op_crud.ClientOpContext | None = None,
    returned_at: datetime | None = None,
    ward_contact_name: str | None = None,
    receipt_checks: StandardChecks | CryoCuffChecks | None = None,
    cuffs_returned: CuffCounts | None = None,
    _commit: bool = True,
) -> BorrowTransaction:
    # See borrow(): ``_commit=False`` is for the D28 correction services only.
    # See borrow(): ``received_by_user_id`` is the recorded operator,
    # ``actor_user_id`` (default: the operator) the audit/status-history actor.
    actor_user_id = actor_user_id if actor_user_id is not None else received_by_user_id
    tx = await transaction_crud.get_by_id(db, transaction_id)
    if tx is None:
        raise TransactionNotFoundError("Transaction not found")

    # Roadmap PR8A Case A -- genuine sequential repeat. The row was already
    # CLOSED before this request even read it (e.g. a refresh/re-submit after
    # a receipt that already completed), so reject immediately without
    # attempting any write. This is a cheap fast-path, NOT the concurrency
    # guard: two truly concurrent requests both read status == OPEN here and
    # both pass this check -- the guard that separates them is the conditional
    # UPDATE below. See docs/design/PR8_IMPLEMENTATION_PLAN.md Section 3.
    #
    # Roadmap PR8C: this is the ONLY branch that may raise
    # TransactionAlreadyReturnedError -- a request reaching here observed a
    # transaction that was not OPEN at the moment it read it, which is a
    # genuine duplicate/repeat submission, not a timing race with another
    # in-flight request.
    if tx.status != TransactionStatus.OPEN:
        if tx.status == TransactionStatus.VOIDED:
            raise TransactionVoidedError("This transaction was voided; no receipt applies to it")
        if tx.close_reason == CLOSE_REASON_REDISPATCH:
            raise TransactionClosedByRedispatchError(
                "This transaction was closed because the equipment was dispatched again; no receipt applies to it"
            )
        raise TransactionAlreadyReturnedError("This transaction has already been returned")

    # Roadmap PR8B: receipt_outcome is a `ReceiptOutcome`, already validated
    # by app.schemas.transaction.ReturnRequest before this service ever
    # runs -- RECEIPT_OUTCOME_TO_STATUS is total over the enum's members, so
    # there is no "unknown outcome" branch to guard here (contrast the
    # pre-PR8B free-form `condition` string, which needed one).
    new_status = RECEIPT_OUTCOME_TO_STATUS[receipt_outcome]

    # Roadmap PR28 (D4/D10/D11), validated before any write: the checklist must
    # match the transaction's kind (historical rows fall back to the equipment's
    # category), and cuffs returned can never exceed what is outstanding.
    checklist_kind = tx.checklist_kind or await checklist_service.kind_for_equipment(db, tx.equipment)
    checklist_service.ensure_kind_matches(receipt_checks, checklist_kind)
    returned_cuffs = cuff_service.resolve_returned(receipt_checks, cuffs_returned)
    if returned_cuffs.total() > 0:
        await cuff_service.validate_returnable(db, tx.id, returned_cuffs)
    if isinstance(receipt_checks, CryoCuffChecks):
        # The stored checklist always carries the counts actually applied.
        receipt_checks = receipt_checks.model_copy(update={"cuffs": returned_cuffs})
    transaction_id = tx.id

    # Roadmap PR8A -- the sole concurrency guard for the receipt race: a
    # conditional close (UPDATE ... WHERE status = 'open') decided by affected
    # -row count. Exactly one of N concurrent receipts for this transaction
    # gets won == True; the rest get won == False.
    won = await transaction_crud.close(
        db, tx, received_by_user_id=received_by_user_id,
        record_save_time=user_agent != LEGACY_SYNC_USER_AGENT,
        receipt_outcome=receipt_outcome.value, notes=notes, returned_at=returned_at,
        receipt_contact_name=ward_contact_name,
        receipt_checks=receipt_checks.model_dump(mode="json") if receipt_checks is not None else None,
    )
    if not won:
        # Roadmap PR8A Case B -- lost a concurrent race. Another request
        # transitioned this row open -> closed between our read (above, which
        # observed OPEN -- otherwise Case A would already have rejected this
        # request) and our own conditional UPDATE. We return here BEFORE any
        # equipment-status, status-history, or audit write, so a losing
        # request produces zero side effects. Roll back the (row-count-zero)
        # UPDATE and the read, then reject.
        #
        # Roadmap PR8C (knowledge/adr/ADR-006-receipt-outcome-contract.md's
        # "Not decided here"): this branch is the ONLY one that may raise
        # ReceiptRaceLostError, a distinct code/class from
        # TransactionAlreadyReturnedError -- this requester did nothing
        # wrong (no prior receipt existed when their request read the row),
        # so "this transaction has already been returned" would misdescribe
        # the cause as a duplicate submission rather than a timing race with
        # another concurrent, equally legitimate request. Same HTTP status
        # (409) as Case A -- both are conflicts with current state -- but a
        # different, stable, machine-readable `code` so a caller (the
        # frontend, or any future API client) can distinguish the two
        # without parsing free-text `detail`.
        await db.rollback()
        raise ReceiptRaceLostError("Another receipt request completed first. Refresh to see the current record.")

    # The conditional UPDATE executed as Core SQL, bypassing the ORM unit of
    # work, so the in-memory ``tx`` still reads OPEN with no receipt fields.
    # Refresh it so every subsequent use -- the equipment transition below and
    # the serialized response -- reflects the committed CLOSED state and never
    # a stale in-memory status (Roadmap PR8A requirement 3). The refresh runs
    # inside this same transaction and therefore sees this session's own,
    # not-yet-committed, winning UPDATE.
    await db.refresh(
        tx,
        attribute_names=[
            "status",
            "returned_at",
            "condition_on_return",
            "received_by_user_id",
            "notes",
            "receipt_contact_name",
            "receipt_checks",
            "receipt_saved_at",
        ],
    )

    equipment = await equipment_crud.get_by_id(db, tx.equipment_id)
    if equipment is None:
        raise EquipmentNotFoundError("Equipment not found")

    await equipment_crud.change_status_for_dispatch_receipt(
        db,
        equipment,
        new_status=new_status,
        changed_by_user_id=actor_user_id,
        reason=f"Returned as {receipt_outcome.value}",
    )
    audit_after = {"receipt_outcome": receipt_outcome.value}
    if receipt_checks is not None:
        audit_after["checklist_kind"] = checklist_kind
    if returned_cuffs.total() > 0:
        try:
            await cuff_service.apply_return(db, tx.id, returned_cuffs)
        except Exception:
            # Includes the close above: all or nothing.
            await db.rollback()
            raise
    if client_op is not None:
        audit_after.update(client_op.audit_fields())
    await audit_crud.create(
        db,
        user_id=actor_user_id,
        action="return",
        entity_type="borrow_transaction",
        entity_id=tx.id,
        after_data=audit_after,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    if returned_cuffs.total() > 0:
        await cuff_service.audit_return(
            db,
            actor_user_id=actor_user_id,
            transaction_id=transaction_id,
            counts=returned_cuffs,
            source="receipt",
            ward_contact_name=ward_contact_name,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    if client_op is not None:
        # Before record_event, which stays the last write (section 6.3).
        await client_op_crud.write_applied(db, client_op, transaction_id=tx.id, occurred_at=tx.returned_at)
    # Roadmap PR25B: last write before commit (see borrow() above).
    # D28: a re-received transaction (after a receipt void) emits a fresh
    # receipt event; export_events allows repeated (transaction, type) rows.
    await export_service.record_event(
        db, transaction_id=tx.id, event_type=EVENT_TYPE_RECEIPT, event_at=tx.returned_at
    )
    if not _commit:
        await db.refresh(tx, attribute_names=["equipment"])
        return tx
    await db.commit()
    await db.refresh(tx, attribute_names=["equipment"])
    await cache_delete_prefix("equipment:search:")
    await cache_delete_prefix("dashboard:")
    return tx


async def correct_ward(
    db: AsyncSession,
    *,
    transaction_id: uuid.UUID,
    new_ward_id: uuid.UUID,
    reason: str,
    actor_user_id: uuid.UUID,
    request: Request | None,
) -> BorrowTransaction:
    """Roadmap PR9A (docs/archive/audits/03-hospital-equipment-pool-workflow-audit.md
    §7 "Ward Recording Rules"): a narrow, audited correction of a
    transaction's recorded destination ward -- distinct from any general
    edit capability, and explicitly NOT ward-transfer tracking (this fixes
    an incorrect original record; the transaction never moves through a
    "ward-to-ward transfer" concept, and no such concept exists anywhere in
    this system). Deliberately has none of return_equipment's lifecycle
    concerns: it never reads or writes ``status``, never touches equipment
    state, and operates identically whether the transaction is OPEN or
    CLOSED -- correcting historical data is valid either way.

    Only ``ward_id`` changes. No other transaction field, lifecycle state,
    dispatch_type/routine_round, or business-event timestamp is read or
    written by this function.
    """
    tx = await transaction_crud.get_by_id(db, transaction_id)
    if tx is None:
        raise TransactionNotFoundError("Transaction not found")

    await ensure_referenced_row_exists(db, Ward, new_ward_id, field_name="ward_id")

    previous_ward_id = tx.ward_id
    if previous_ward_id == new_ward_id:
        # No audit entry: rejected before any write is attempted, so there is
        # no before/after transition to record (see WardCorrectionNoOpError's
        # docstring).
        raise WardCorrectionNoOpError("The submitted ward is already recorded for this transaction.")

    # Roadmap PR9A concurrency requirement -- the same conditional-UPDATE
    # shape Roadmap PR8A established for close(), applied to ward_id: decide
    # the outcome by affected-row count against the ward_id value read above,
    # never by an unconditional UPDATE trusting the in-memory read to still
    # be current.
    won = await transaction_crud.correct_ward(db, tx, expected_ward_id=previous_ward_id, new_ward_id=new_ward_id)
    if not won:
        # A concurrent correction changed ward_id between this request's read
        # (previous_ward_id, above) and its own conditional UPDATE. Roll back
        # before any audit write -- exactly the same "loser produces zero
        # side effects" shape as ReceiptRaceLostError, but a distinct
        # exception/code: reusing a receipt-flow code here would misdescribe
        # the cause to any caller inspecting the response.
        await db.rollback()
        raise WardCorrectionConflictError(
            "Another correction updated this transaction's ward first. Refresh to see the current record."
        )

    # correct_ward() executed as Core SQL, bypassing the ORM unit of work, so
    # the in-memory `tx` still reads the pre-correction ward_id. Refresh so
    # the response reflects committed state, never a stale value (mirrors
    # return_equipment's identical requirement after a winning close()).
    await db.refresh(tx, attribute_names=["ward_id"])

    # Exactly one audit entry per successful correction, via the canonical
    # PR3 writer (app.core.audit.record_audit_event) -- not the lower-level
    # audit_crud.create this module's older borrow()/return_equipment() call
    # sites use, since only record_audit_event captures the full
    # request/correlation-id and IP/user-agent metadata this action's audit
    # requirement calls for. before/after record exactly the two ward values
    # and the mandatory reason -- no other, unrestricted request data.
    await record_audit_event(
        db,
        actor_user_id=actor_user_id,
        action=AUDIT_ACTION_WARD_CORRECTION,
        entity_type=AUDIT_ENTITY_BORROW_TRANSACTION,
        entity_id=tx.id,
        before={"ward_id": str(previous_ward_id) if previous_ward_id else None},
        after={"ward_id": str(new_ward_id), "reason": reason},
        request=request,
    )
    # Atomic: the ward_id UPDATE above and the audit INSERT are both only
    # flushed, not committed, until this single commit -- either both
    # persist or (on any exception before this point) neither does, since
    # they share the same database transaction.
    await db.commit()
    await db.refresh(tx, attribute_names=["equipment"])
    return tx


# ---------------------------------------------------------------------------
# Owner Governance 2026-11-27 (D28): entry-error correction.
#
# undo / void / change_device / switch_action live in the dispatch/receipt
# service layer (never manual status maintenance). Every action:
#   - touches only the device's LATEST non-voided transaction;
#   - is refused (409, nothing changed) when the device's current state is no
#     longer the state the event produced;
#   - is permitted for the Administrator always, for Equipment Pool staff only
#     on their own entry within the same PR16 business_date + shift as the
#     event (undo: the operator who saved it, inside the undo window, not
#     shift-limited); Read Only never;
#   - writes exactly one audit entry (never an HN) in the same commit.
# The event a correction targets is derived from the transaction: an OPEN
# transaction is a dispatch; a CLOSED transaction with a receipt is a receipt.
# ---------------------------------------------------------------------------

UNDO_WINDOW_DISPATCH = timedelta(seconds=120)
UNDO_WINDOW_RECEIPT = timedelta(seconds=30)
# Receipts replayed by the legacy-sheet sync (user agent set by
# app.services.legacy_sheet_sync.runner.USER_AGENT) record no ``receipt_saved_at``
# and so can never be undone: the sync user is not an operator who "just saved".
LEGACY_SYNC_USER_AGENT = "legacy-sheet-sync"
UNDO_REASON = "เลิกทำ"
REASON_MAX_LENGTH = 500

EVENT_KIND_DISPATCH = "dispatch"
EVENT_KIND_RECEIPT = "receipt"

AUDIT_ACTION_UNDO = "transaction_undo"
AUDIT_ACTION_VOID = "transaction_void"
AUDIT_ACTION_CHANGE_DEVICE = "transaction_change_device"
AUDIT_ACTION_SWITCH_ACTION = "transaction_switch_action"

# Equipment state each receipt outcome produced (pre-PR8B 'available' = usable).
_STATE_AFTER_RECEIPT = {
    "usable": EquipmentStatus.AVAILABLE_AT_POOL,
    "available": EquipmentStatus.AVAILABLE_AT_POOL,
    "defective": EquipmentStatus.UNAVAILABLE_DEFECTIVE,
}


@dataclass
class _CorrectionTarget:
    tx: BorrowTransaction
    equipment: object
    event: str
    role: str


def _split_return_note(notes: str | None) -> tuple[str | None, str | None]:
    """(dispatch notes, receipt note). close() appends the receipt note as
    "\n[Return] <note>"; split only on the LAST such marker so a dispatch note
    that itself contains "[Return] " is never cut."""
    if not notes or "\n[Return] " not in notes:
        return notes, None
    head, tail = notes.rsplit("\n[Return] ", 1)
    return (head.strip() or None), (tail.strip() or None)


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _clean_reason(reason: str | None) -> str:
    cleaned = (reason or "").strip()
    if not cleaned:
        raise InvalidInputError("A reason is required.")
    if len(cleaned) > REASON_MAX_LENGTH:
        raise InvalidInputError(f"The reason must be at most {REASON_MAX_LENGTH} characters.")
    return cleaned


def _snapshot(tx: BorrowTransaction) -> dict:
    """Audit before-image. Receipt fields are kept here when a receipt is
    voided. Never contains an HN (only the has_hn indicator)."""
    return {
        "transaction_no": tx.transaction_no,
        "status": tx.status.value,
        "equipment_id": str(tx.equipment_id),
        "ward_id": str(tx.ward_id) if tx.ward_id else None,
        "borrowed_at": tx.borrowed_at.isoformat() if tx.borrowed_at else None,
        "returned_at": tx.returned_at.isoformat() if tx.returned_at else None,
        "receipt_outcome": tx.condition_on_return,
        "received_by_user_id": str(tx.received_by_user_id) if tx.received_by_user_id else None,
        "receipt_contact_name": tx.receipt_contact_name,
        "receipt_keyer_label": tx.receipt_keyer_label,
        "receipt_checks": tx.receipt_checks,
        "receipt_note": _split_return_note(tx.notes)[1] if tx.returned_at else None,
        "close_reason": tx.close_reason,
        "has_hn": tx.has_hn,
    }


async def _prepare_correction(
    db: AsyncSession, *, transaction_id: uuid.UUID, user, undo: bool
) -> _CorrectionTarget:
    role = await db.get(Role, user.role_id)
    role_name = role.name if role is not None else ""
    if role_name not in (ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF):
        raise CorrectionNotPermittedError("This role may not correct transactions.")

    tx = await transaction_crud.get_by_id(db, transaction_id)
    if tx is None:
        raise TransactionNotFoundError("Transaction not found")
    if tx.status == TransactionStatus.VOIDED:
        raise TransactionVoidedError("This transaction was already voided.")
    if tx.status == TransactionStatus.OPEN:
        event = EVENT_KIND_DISPATCH
    elif tx.returned_at is not None:
        event = EVENT_KIND_RECEIPT
    else:
        # Closed by D8 re-dispatch with no receipt: a later dispatch exists.
        raise CorrectionNotLatestError("Only the device's latest transaction can be corrected.")

    operator_id = tx.borrower_user_id if event == EVENT_KIND_DISPATCH else tx.received_by_user_id
    now = datetime.now(timezone.utc)
    if undo:
        if operator_id != user.id:
            raise CorrectionNotPermittedError("Only the operator who saved this entry may undo it.")
    elif role_name != ROLE_ADMINISTRATOR:
        event_at = tx.borrowed_at if event == EVENT_KIND_DISPATCH else tx.returned_at
        if operator_id != user.id or business_date_and_shift(event_at) != business_date_and_shift(now):
            raise CorrectionNotPermittedError(
                "Equipment Pool staff may correct only their own entries within the same shift; "
                "ask an administrator."
            )

    latest = await transaction_crud.latest_non_voided_for_equipment(db, tx.equipment_id)
    if latest is None or latest.id != tx.id:
        raise CorrectionNotLatestError("Only the device's latest transaction can be corrected.")

    equipment = await equipment_crud.get_by_id(db, tx.equipment_id)
    if equipment is None:
        raise EquipmentNotFoundError("Equipment not found")
    if event == EVENT_KIND_DISPATCH:
        expected = EquipmentStatus.ISSUED_TO_WARD
    else:
        expected = _STATE_AFTER_RECEIPT.get(tx.condition_on_return)
    if expected is None or equipment.status != expected:
        raise CorrectionStateChangedError(
            "The device's state changed after this entry; an administrator must resolve it first.",
            details={
                "equipment_status": equipment.status.value,
                "expected_status": expected.value if expected is not None else None,
            },
        )

    if undo:
        base = tx.created_at if event == EVENT_KIND_DISPATCH else tx.receipt_saved_at
        window = UNDO_WINDOW_DISPATCH if event == EVENT_KIND_DISPATCH else UNDO_WINDOW_RECEIPT
        if base is None or now - _aware(base) > window:
            raise UndoWindowExpiredError(
                "The undo window has passed; void the entry with a reason instead.",
                details={"window_seconds": int(window.total_seconds())},
            )
    return _CorrectionTarget(tx=tx, equipment=equipment, event=event, role=role_name)


async def _void_event(
    db: AsyncSession,
    target: _CorrectionTarget,
    *,
    user,
    reason: str,
    corrected_by_transaction_id: uuid.UUID | None = None,
    clear_hn: bool = False,
    reopen_transaction_id: uuid.UUID | None = None,
) -> dict:
    """Voids the targeted event inside the caller's database transaction (no
    commit) and returns the audit ``after`` facts. A dispatch becomes a
    ``voided`` transaction, the device returns to its stored prior state and a
    transaction the dispatch closed by D8 re-dispatch reopens. A receipt is
    reopened (receipt fields cleared) and the device returns to ISSUED_TO_WARD.
    ``reopen_transaction_id`` lets switch_action name the transaction to reopen
    for a legacy dispatch that has no stored ``closed_by_redispatch_...``."""
    tx, equipment = target.tx, target.equipment
    after: dict = {"event": target.event, "reason": reason}
    if target.event == EVENT_KIND_DISPATCH:
        reopen_id = reopen_transaction_id or tx.closed_by_redispatch_transaction_id
        if reopen_id is None:
            # Legacy dispatch without the stored link: the transaction it closed
            # by re-dispatch is the device's immediately preceding one.
            earlier = await transaction_crud.previous_redispatch_closed(db, tx)
            reopen_id = earlier.id if earlier is not None else None
        if reopen_id is None and tx.prior_equipment_status == EquipmentStatus.ISSUED_TO_WARD.value:
            raise CorrectionStateChangedError(
                "This dispatch followed an open transaction that cannot be identified; "
                "an administrator must resolve it first."
            )
        won = await transaction_crud.void_open_dispatch(
            db,
            tx,
            voided_by_user_id=user.id,
            reason=reason,
            corrected_by_transaction_id=corrected_by_transaction_id,
            clear_hn=clear_hn,
        )
        if not won:
            await db.rollback()
            raise CorrectionConflictError("The transaction was changed by someone else. Refresh and retry.")
        if reopen_id is not None:
            if not await transaction_crud.reopen_redispatch_closed(db, reopen_id):
                await db.rollback()
                raise CorrectionConflictError("The earlier transaction was changed by someone else. Refresh and retry.")
            restore = EquipmentStatus.ISSUED_TO_WARD
            after["reopened_transaction_id"] = str(reopen_id)
        else:
            try:
                restore = EquipmentStatus(tx.prior_equipment_status) if tx.prior_equipment_status else None
            except ValueError:
                restore = None
            # Legacy rows (no stored prior state) restore to the pool; a stored
            # ISSUED_TO_WARD without a closed transaction cannot be restored.
            if restore is None or restore == EquipmentStatus.ISSUED_TO_WARD:
                restore = EquipmentStatus.AVAILABLE_AT_POOL
    else:
        # close() appended the receipt note to the dispatch notes: strip it.
        notes = _split_return_note(tx.notes)[0]
        returned_cuffs = CuffCounts()
        if isinstance(tx.receipt_checks, dict) and tx.receipt_checks.get("kind") == "cryo_cuff":
            try:
                returned_cuffs = CryoCuffChecks.model_validate(tx.receipt_checks).cuffs
            except Exception:  # malformed stored JSON must not block a correction
                returned_cuffs = CuffCounts()
        if not await transaction_crud.reopen_received(db, tx, notes=notes or None):
            await db.rollback()
            raise CorrectionConflictError("The transaction was changed by someone else. Refresh and retry.")
        if returned_cuffs.total() > 0:
            await cuff_service.reverse_receipt_return(db, tx.id, returned_cuffs)
        restore = EquipmentStatus.ISSUED_TO_WARD
    try:
        await equipment_crud.change_status_for_dispatch_receipt(
            db,
            equipment,
            new_status=restore,
            changed_by_user_id=user.id,
            reason=f"Correction: {target.event} voided",
        )
    except EquipmentStatusChangedError:
        await db.rollback()
        raise CorrectionStateChangedError(
            "The device's state changed while the correction was processed; nothing was changed."
        ) from None
    await db.refresh(tx)
    after["equipment_status_restored_to"] = restore.value
    # D28 export API: withdraw (inside the hold-back window) or compensate
    # (already visible) the voided event. Touches no HN.
    await export_service.record_void(db, tx=tx, voided_kind=target.event)
    return after


async def _finish(db: AsyncSession, transaction_id: uuid.UUID) -> BorrowTransaction:
    await db.commit()
    await cache_delete_prefix("equipment:search:")
    await cache_delete_prefix("dashboard:")
    db.expire_all()
    tx = await transaction_crud.get_by_id(db, transaction_id)
    assert tx is not None
    return tx


async def _audit(db, *, user, action, tx, before, after, request) -> None:
    await record_audit_event(
        db,
        actor_user_id=user.id,
        action=action,
        entity_type=AUDIT_ENTITY_BORROW_TRANSACTION,
        entity_id=tx.id,
        before=before,
        after=after,
        request=request,
    )


async def undo(db: AsyncSession, *, transaction_id: uuid.UUID, user, request: Request | None = None) -> BorrowTransaction:
    """D28 Layer 2. The operator who saved the entry, within 120 s of saving a
    dispatch (``created_at``) or 30 s of saving a receipt (``receipt_saved_at``).

    The window is measured from the SERVER save time, never from the business
    event time: ``borrowed_at``/``returned_at`` can be in the past (legacy
    sheet sync, offline queue). A legacy receipt without ``receipt_saved_at``
    is not undoable. Not limited by the end of the shift. System reason
    "เลิกทำ"; otherwise identical to a void."""
    target = await _prepare_correction(db, transaction_id=transaction_id, user=user, undo=True)
    before = _snapshot(target.tx)
    after = await _void_event(db, target, user=user, reason=UNDO_REASON)
    after["undo"] = True
    await _audit(db, user=user, action=AUDIT_ACTION_UNDO, tx=target.tx, before=before, after=after, request=request)
    return await _finish(db, transaction_id)


async def void(
    db: AsyncSession, *, transaction_id: uuid.UUID, user, reason: str, request: Request | None = None
) -> BorrowTransaction:
    """D28 Layer 3 "Void (ยกเลิกรายการ)": mandatory reason, latest transaction
    only, state guard, role/shift permission, one atomic audit entry."""
    reason = _clean_reason(reason)
    target = await _prepare_correction(db, transaction_id=transaction_id, user=user, undo=False)
    before = _snapshot(target.tx)
    after = await _void_event(db, target, user=user, reason=reason)
    await _audit(db, user=user, action=AUDIT_ACTION_VOID, tx=target.tx, before=before, after=after, request=request)
    return await _finish(db, transaction_id)


def _client_meta(request: Request | None) -> tuple[str | None, str | None]:
    if request is None:
        return None, None
    ua = request.headers.get("user-agent")
    return (request.client.host if request.client else None), (ua[:255] if ua else None)


def _parse_checks(raw: dict | None):
    return TypeAdapter(Checks).validate_python(raw) if raw else None


async def change_device(
    db: AsyncSession,
    *,
    transaction_id: uuid.UUID,
    new_equipment_id: str,
    user,
    reason: str,
    acknowledge_status_warning: bool = False,
    request: Request | None = None,
) -> tuple[BorrowTransaction, BorrowTransaction]:
    """D28 "Change device (เปลี่ยนเครื่อง)": voids the event on the wrong device
    and records the same event (same time, ward, keyer label, contact name,
    checks, operator) on the correct device through the normal borrow()/
    return_equipment() rules, in ONE database transaction. A dispatch's HN is
    decrypted and re-encrypted on the server (never leaves it) and cleared on
    the voided row. Returns (transaction on the wrong device, new transaction)."""
    reason = _clean_reason(reason)
    ip, ua = _client_meta(request)
    target = await _prepare_correction(db, transaction_id=transaction_id, user=user, undo=False)
    tx = target.tx
    new_equipment = await equipment_crud.get_by_id(db, parse_uuid(new_equipment_id, "equipment_id"))
    if new_equipment is None:
        raise EquipmentNotFoundError("Equipment not found")
    if new_equipment.id == tx.equipment_id:
        raise InvalidInputError("Choose a different device.")
    before = _snapshot(tx)
    old = {
        "ward_id": tx.ward_id,
        "borrowed_at": tx.borrowed_at,
        "returned_at": tx.returned_at,
        "borrower_user_id": tx.borrower_user_id,
        "received_by_user_id": tx.received_by_user_id,
        "dispatch_type": tx.dispatch_type,
        "routine_round": tx.routine_round,
        "department_id": tx.department_id,
        "phone_number": tx.phone_number,
        "pickup_location_id": tx.pickup_location_id,
        "dropoff_location_id": tx.dropoff_location_id,
        "notes": tx.notes,
        "receipt_note": _split_return_note(tx.notes)[1] if tx.returned_at else None,
        "dispatch_contact_name": tx.dispatch_contact_name,
        "receipt_contact_name": tx.receipt_contact_name,
        "dispatch_keyer_label": tx.dispatch_keyer_label,
        "receipt_keyer_label": tx.receipt_keyer_label,
        "dispatch_checks": tx.dispatch_checks,
        "receipt_checks": tx.receipt_checks,
        "outcome": tx.condition_on_return,
    }
    moved_hn = False
    hn_plain: str | None = None
    if target.event == EVENT_KIND_DISPATCH and tx.has_hn:
        ciphertext = (
            await db.execute(select(BorrowTransaction.hn_ciphertext).where(BorrowTransaction.id == tx.id))
        ).scalar_one_or_none()
        if ciphertext:
            hn_plain = hn_crypto.decrypt_hn(ciphertext)  # server-side only
            moved_hn = True
    try:
        receipt_target_tx = None
        if target.event == EVENT_KIND_RECEIPT:
            receipt_target_tx = await transaction_crud.get_open_transaction_for_equipment(db, new_equipment.id)
            if receipt_target_tx is None:
                raise InvalidInputError("The correct device has no open dispatch to receive.")
            try:
                outcome = ReceiptOutcome("usable" if old["outcome"] == "available" else old["outcome"])
            except ValueError:
                raise InvalidInputError("This receipt's outcome cannot be carried to another device.") from None
            receipt_target_id = receipt_target_tx.id
        after = await _void_event(db, target, user=user, reason=reason, clear_hn=moved_hn)
        if target.event == EVENT_KIND_DISPATCH:
            new_tx = await borrow(
                db,
                equipment_id=str(new_equipment.id),
                borrower_user_id=old["borrower_user_id"],
                actor_user_id=user.id,
                ward_id=str(old["ward_id"]) if old["ward_id"] else "",
                dispatch_type=old["dispatch_type"],
                routine_round=old["routine_round"],
                department_id=str(old["department_id"]) if old["department_id"] else None,
                phone_number=old["phone_number"],
                pickup_location_id=str(old["pickup_location_id"]) if old["pickup_location_id"] else None,
                dropoff_location_id=str(old["dropoff_location_id"]) if old["dropoff_location_id"] else None,
                notes=old["notes"],
                ip_address=ip,
                user_agent=ua,
                borrowed_at=old["borrowed_at"],
                acknowledge_status_warning=acknowledge_status_warning,
                ward_contact_name=old["dispatch_contact_name"],
                dispatch_checks=_parse_checks(old["dispatch_checks"]),
                hn=hn_plain,
                _commit=False,
            )
            new_tx.dispatch_keyer_label = old["dispatch_keyer_label"]
            await transaction_crud.set_corrected_by(db, tx, new_tx.id)
        else:
            new_tx = await return_equipment(
                db,
                transaction_id=receipt_target_id,
                receipt_outcome=outcome,
                notes=old["receipt_note"],
                received_by_user_id=old["received_by_user_id"],
                ip_address=ip,
                user_agent=ua,
                actor_user_id=user.id,
                returned_at=old["returned_at"],
                ward_contact_name=old["receipt_contact_name"],
                receipt_checks=_parse_checks(old["receipt_checks"]),
                _commit=False,
            )
            new_tx.receipt_keyer_label = old["receipt_keyer_label"]
        after.update({"new_transaction_id": str(new_tx.id), "new_equipment_id": str(new_equipment.id)})
        if moved_hn:
            after["hn_moved"] = True  # indicator only, never the value
        await _audit(
            db, user=user, action=AUDIT_ACTION_CHANGE_DEVICE, tx=tx, before=before, after=after, request=request
        )
    except Exception:
        await db.rollback()
        raise
    new_id = new_tx.id
    await _finish(db, tx.id)
    new_tx = await transaction_crud.get_by_id(db, new_id)
    return await transaction_crud.get_by_id(db, transaction_id), new_tx


async def switch_action(
    db: AsyncSession,
    *,
    transaction_id: uuid.UUID,
    user,
    reason: str,
    outcome: ReceiptOutcome = ReceiptOutcome.USABLE,
    ward_id: str | None = None,
    request: Request | None = None,
) -> tuple[BorrowTransaction, BorrowTransaction]:
    """D28 "Switch action (สลับงาน)", one database transaction.

    - dispatch -> receipt: offered only when the wrong dispatch had closed an
      earlier transaction by re-dispatch (``closed_by_redispatch_transaction_id``,
      else the device's earlier re-dispatch-closed transaction). The dispatch is
      voided (that transaction reopens) and then received at the dispatch's
      time with ``outcome`` (default usable). Returns (voided dispatch, the
      received transaction).
    - receipt -> dispatch: the receipt is voided (its transaction reopens) and
      a dispatch to ``ward_id`` is recorded at the receipt's time; per D8 it
      closes the reopened transaction as a re-dispatch. Returns (the reopened
      transaction, the new dispatch).
    The operator, contact name and BME keyer label of the original entry carry
    over. Accessory checks are not carried (they belong to the other action)."""
    reason = _clean_reason(reason)
    ip, ua = _client_meta(request)
    target = await _prepare_correction(db, transaction_id=transaction_id, user=user, undo=False)
    tx = target.tx
    before = _snapshot(tx)
    old_borrowed_at, old_returned_at = tx.borrowed_at, tx.returned_at
    old_borrower, old_receiver = tx.borrower_user_id, tx.received_by_user_id
    old_dispatch_contact, old_receipt_contact = tx.dispatch_contact_name, tx.receipt_contact_name
    old_dispatch_label, old_receipt_label = tx.dispatch_keyer_label, tx.receipt_keyer_label
    try:
        if target.event == EVENT_KIND_DISPATCH:
            predecessor_id = tx.closed_by_redispatch_transaction_id
            if predecessor_id is None:
                earlier = await transaction_crud.previous_redispatch_closed(db, tx)
                predecessor_id = earlier.id if earlier is not None else None
            if predecessor_id is None:
                raise SwitchActionNotAvailableError(
                    "This dispatch did not follow an open transaction, so it cannot become a receipt."
                )
            after = await _void_event(
                db,
                target,
                user=user,
                reason=reason,
                corrected_by_transaction_id=predecessor_id,
                reopen_transaction_id=predecessor_id,
            )
            # The reopen above was a Core UPDATE: load fresh state for the receipt.
            await db.get(BorrowTransaction, predecessor_id, populate_existing=True)
            result_tx = await return_equipment(
                db,
                transaction_id=predecessor_id,
                receipt_outcome=outcome,
                notes=None,
                received_by_user_id=old_borrower,
                ip_address=ip,
                user_agent=ua,
                actor_user_id=user.id,
                returned_at=old_borrowed_at,
                ward_contact_name=old_dispatch_contact,
                _commit=False,
            )
            result_tx.receipt_keyer_label = old_dispatch_label
            after["switched_to"] = EVENT_KIND_RECEIPT
            after["receipt_outcome"] = outcome.value
        else:
            if not ward_id:
                raise InvalidInputError("A ward is required to record the dispatch.")
            after = await _void_event(db, target, user=user, reason=reason)
            result_tx = await borrow(
                db,
                equipment_id=str(tx.equipment_id),
                borrower_user_id=old_receiver,
                actor_user_id=user.id,
                ward_id=ward_id,
                dispatch_type=DispatchType.ON_DEMAND,
                routine_round=None,
                department_id=None,
                phone_number=None,
                pickup_location_id=None,
                dropoff_location_id=None,
                notes=None,
                ip_address=ip,
                user_agent=ua,
                borrowed_at=old_returned_at,
                acknowledge_status_warning=True,  # the reopened transaction is closed by D8 re-dispatch
                expected_open_transaction_id=str(tx.id),
                ward_contact_name=old_receipt_contact,
                _commit=False,
            )
            result_tx.dispatch_keyer_label = old_receipt_label
            after["switched_to"] = EVENT_KIND_DISPATCH
        after["new_transaction_id"] = str(result_tx.id)
        await _audit(
            db, user=user, action=AUDIT_ACTION_SWITCH_ACTION, tx=tx, before=before, after=after, request=request
        )
    except Exception:
        await db.rollback()
        raise
    result_id = result_tx.id
    await _finish(db, tx.id)
    return await transaction_crud.get_by_id(db, transaction_id), await transaction_crud.get_by_id(db, result_id)
