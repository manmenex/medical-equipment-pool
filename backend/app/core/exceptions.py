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


class PdfRenderTimeoutError(DomainError):
    """Roadmap PR18D review 4838921407 (H1): design §18 requires PDF
    rendering to have "explicit time, memory, and concurrency bounds" and
    for a request exceeding a configured limit to "fail before rendering
    [completes]; it is never silently truncated." Raised by
    ``app.services.report_pdf_service.render_pdf_bounded`` when a single
    render does not complete within ``RENDER_TIMEOUT_SECONDS``. `503`
    (not a `4xx`) because the request itself was well-formed -- rendering
    is a transient resource condition the caller can retry, not a client
    input problem."""

    code = "PDF_RENDER_TIMEOUT"
    status_code = 503


class XlsxRenderTimeoutError(DomainError):
    """Roadmap PR18E review round 1 (H2): mirrors `PdfRenderTimeoutError`'s
    rationale for the Excel adapter -- design §18 requires "explicit time,
    memory, and concurrency bounds" for every renderer, not only PDF.
    Raised by ``app.services.report_xlsx_service.build_workbook_bounded``
    when a single `.xlsx` generation (including time spent queued for
    renderer capacity) does not complete within
    ``RENDER_TIMEOUT_SECONDS``. `503` (not a `4xx`) because the request
    itself was well-formed -- generation capacity is a transient resource
    condition the caller can retry, not a client input problem."""

    code = "XLSX_RENDER_TIMEOUT"
    status_code = 503


class ImportSessionNotFoundError(DomainError):
    """Roadmap PR19A (Legacy Import Foundation): raised when an
    ``import_session_id`` in a request path does not resolve to an existing
    `app.models.import_session.ImportSession` row."""

    code = "IMPORT_SESSION_NOT_FOUND"
    status_code = 404


class ImportAdapterNotRegisteredError(DomainError):
    """Roadmap PR19A: raised when a session's ``dataset_type`` has no
    `app.services.import_foundation.ImportAdapter` registered for it.
    Every dataset type this foundation slice's own tests use is
    intentionally unregistered in production — the concrete adapters for
    real legacy datasets (Equipment Master, Receive history, Issue history)
    are Roadmap PR20/PR21 scope, not this slice's. A caller reaching this
    error against a real dataset type is the expected, honest outcome until
    that future slice registers its adapter."""

    code = "IMPORT_ADAPTER_NOT_REGISTERED"
    status_code = 422


class ImportSessionStateError(DomainError):
    """Roadmap PR19A: raised when a request would move an
    `ImportSession` through a transition its current
    `app.models.import_session.ImportSessionStatus` does not allow (e.g.
    dry-run before validation has completed, or any state-changing call
    against an already-terminal session). Mirrors this codebase's existing
    conditional-state-machine-guard convention (e.g.
    ``WardCorrectionConflictError``) applied to import sessions instead of
    a transaction/ward."""

    code = "IMPORT_SESSION_INVALID_STATE"
    status_code = 409


class ImportAdapterNotImplementedError(DomainError):
    """Roadmap PR19A: raised by `app.services.import_foundation.
    ImportAdapter`'s base `plan_dry_run`/`execute` hooks. This is the
    explicit, structural proof that dry-run and execution are wired
    end-to-end (state checks, `ImportJob` bookkeeping, transaction
    boundaries) without any concrete dataset import being implemented in
    this slice — every registered adapter must override these hooks to do
    real work; the foundation itself never can. ``501`` (not a `4xx`)
    because the request was well-formed and the session was in the right
    state; the server genuinely does not implement this operation for this
    dataset type yet."""

    code = "IMPORT_ADAPTER_NOT_IMPLEMENTED"
    status_code = 501


class ImportExecutionFailedError(DomainError):
    """Roadmap PR19A: raised when an adapter's ``execute()`` hook fails
    after dry-run has already succeeded. The entire execution transaction
    is rolled back before this is raised (see
    `app.services.import_foundation.run_execute`) — never a partial write,
    mirroring Roadmap PR12's ``ImportCommitFailedError`` precedent for the
    same "no partial silent import" invariant applied to this framework."""

    code = "IMPORT_EXECUTION_FAILED"
    status_code = 500


class ConflictError(DomainError):
    """Generic safe fallback for an IntegrityError that could not be classified.

    Used only when the underlying database driver gives us no reliable way
    to tell whether a constraint violation was a duplicate key, a bad
    reference, or something else — see app.core.db_errors.
    """

    code = "CONFLICT"
    status_code = 409
