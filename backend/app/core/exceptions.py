class DomainError(Exception):
    code = "DOMAIN_ERROR"
    status_code = 400

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class EquipmentNotFoundError(DomainError):
    code = "EQUIPMENT_NOT_FOUND"
    status_code = 404


class EquipmentNotAvailableError(DomainError):
    code = "EQUIPMENT_NOT_AVAILABLE"
    status_code = 409


class TransactionNotFoundError(DomainError):
    code = "TRANSACTION_NOT_FOUND"
    status_code = 404


class TransactionAlreadyReturnedError(DomainError):
    """Raised for a genuine sequential repeat receipt: the transaction's
    ``status`` was already not ``OPEN`` *before* this request's own read
    (app.services.borrow_service.return_equipment's Case A) -- e.g. a
    reload/re-submit of a receipt form after the receipt already
    completed. See ReceiptRaceLostError for the sibling case this request
    must not be confused with."""

    code = "TRANSACTION_ALREADY_RETURNED"
    status_code = 409


class ReceiptRaceLostError(DomainError):
    """Roadmap PR8C (knowledge/adr/ADR-006-receipt-outcome-contract.md's
    "Not decided here"): raised when this request's own read observed the
    transaction as OPEN, but a concurrent request won Roadmap PR8A's
    conditional-close race and closed it first -- app.services.
    borrow_service.return_equipment's Case B. Deliberately a distinct
    class/code from TransactionAlreadyReturnedError: the requester did
    nothing wrong here (no prior receipt existed when they submitted
    theirs), so "this transaction has already been returned" would be an
    inaccurate description of the cause, even though the HTTP status
    (409 Conflict) is the same for both -- see docs/design/
    PR8_IMPLEMENTATION_PLAN.md Section 6."""

    code = "RECEIPT_RACE_LOST"
    status_code = 409


class DuplicateError(DomainError):
    code = "DUPLICATE"
    status_code = 409


class ResourceNotFoundError(DomainError):
    code = "RESOURCE_NOT_FOUND"
    status_code = 404


class InvalidInputError(DomainError):
    code = "INVALID_INPUT"
    status_code = 400


class MalformedQrCodeError(DomainError):
    """Raised when a scanned QR payload cannot be read as a valid Item No.

    Deliberately a 400 DomainError (client-side/input problem — the scanner
    picked up something that isn't one of this hospital's equipment QR
    labels), never a 404 EquipmentNotFoundError (which means the QR *was*
    a well-formed Item No but no equipment record matches it).
    """

    code = "MALFORMED_QR_CODE"
    status_code = 400


class InvalidStatusTransitionError(DomainError):
    """Raised when a status change would move equipment between states its
    caller's transition authority does not allow (e.g. DECOMMISSIONED ->
    any; AVAILABLE_AT_POOL -> AVAILABLE_AT_POOL; or, from the generic
    admin/BME endpoint specifically, any transition into or out of
    ISSUED_TO_WARD, which is dispatch/receipt-only). See
    app.models.equipment.DISPATCH_RECEIPT_TRANSITIONS and
    .MANUAL_LIFECYCLE_TRANSITIONS.
    """

    code = "INVALID_STATUS_TRANSITION"
    status_code = 409


class WardCorrectionNoOpError(DomainError):
    """Roadmap PR9A (docs/audits/03-hospital-equipment-pool-workflow-audit.md
    §7 "Ward Recording Rules"): raised when a ward-correction request's
    ``ward_id`` equals the transaction's current ``ward_id`` at the moment
    it was read. Not an error about the target ward or the transaction --
    the request is well-formed and both reference real rows -- it is
    rejected because applying it would not correct anything: there is no
    prior-vs-corrected distinction to record, and writing an audit entry
    for a no-op would misrepresent that a change happened. Deliberately a
    distinct code from ``TRANSACTION_ALREADY_RETURNED``/
    ``RECEIPT_RACE_LOST`` (Roadmap PR8C) -- this is a same-ward no-op, not
    a receipt-flow conflict, and must not be confused with either."""

    code = "WARD_CORRECTION_NOOP"
    status_code = 409


class WardCorrectionConflictError(DomainError):
    """Roadmap PR9A: raised when this request's conditional ward-correction
    update affected zero rows -- the transaction's ``ward_id`` was no
    longer the value this request read at the start (a concurrent
    correction won first). Mirrors ``ReceiptRaceLostError``'s
    conditional-UPDATE-loses-the-race shape (Roadmap PR8A/PR8C) applied to
    a different column, but is deliberately a distinct code: reusing a
    receipt-flow code here would misdescribe the cause to a caller
    inspecting the response, and the two flows must remain independently
    evolvable. The requester did nothing wrong -- their read was accurate
    when taken -- so the caller should refresh the transaction and decide
    whether to resubmit against the new current state, not retry blindly."""

    code = "WARD_CORRECTION_CONFLICT"
    status_code = 409


class ExportTooLargeError(DomainError):
    """Roadmap PR18B (docs/design/PR18_PRINTING_EXPORT_PLAN.md §8/§18/§23,
    Owner Decision #3): raised when a bulk report export/print request's
    full matching-row count exceeds the approved synchronous row limit
    (``app.services.report_export_service.MAX_EXPORT_ROWS``). Deliberately
    rejects the whole request rather than silently truncating -- a
    truncated hospital operational report that looks complete would be
    worse than an explicit refusal (design §8). The caller should narrow
    the applied filters (date range, ward, category, etc.) and retry."""

    code = "EXPORT_TOO_LARGE"
    status_code = 422


class ConflictError(DomainError):
    """Generic safe fallback for an IntegrityError that could not be classified.

    Used only when the underlying database driver gives us no reliable way
    to tell whether a constraint violation was a duplicate key, a bad
    reference, or something else — see app.core.db_errors.
    """

    code = "CONFLICT"
    status_code = 409
