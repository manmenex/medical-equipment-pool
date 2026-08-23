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


class ConflictError(DomainError):
    """Generic safe fallback for an IntegrityError that could not be classified.

    Used only when the underlying database driver gives us no reliable way
    to tell whether a constraint violation was a duplicate key, a bad
    reference, or something else — see app.core.db_errors.
    """

    code = "CONFLICT"
    status_code = 409


class ImportSessionNotFoundError(DomainError):
    """Roadmap PR19A1 (docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md
    §23) — the session id in the path does not exist."""

    code = "IMPORT_SESSION_NOT_FOUND"
    status_code = 404


class ImportSessionInvalidStateError(DomainError):
    """§23 — the requested operation is invalid from the session's current
    status. One consolidated code per class of problem, per §23 — the
    `detail` string carries the specifics (e.g. which status was expected)."""

    code = "IMPORT_SESSION_INVALID_STATE"
    status_code = 409


class ImportSourceMismatchError(DomainError):
    """§15.2 — a source registration/correction's identity fingerprint
    differs from what is already frozen for this session, or a CAS
    correction attempt lost the race to a concurrent freeze. The row is
    never mutated in either case."""

    code = "IMPORT_SOURCE_MISMATCH"
    status_code = 409


class ImportSourceNotRegisteredError(DomainError):
    """Roadmap PR19A2 (design §6, §23) — `validate` was called with no
    `ImportSource` row registered for this session at all. Checked before
    any CAS transition is attempted, per §6's validation-gate contract."""

    code = "IMPORT_SOURCE_NOT_REGISTERED"
    status_code = 409


class ImportSourceRegistrationMethodNotAllowedError(DomainError):
    """Roadmap PR20A (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md
    §6.2) — the existing metadata-only `POST /import-sessions/{id}/source`
    endpoint was called for a session whose `dataset_type` requires the
    single authoritative, server-checksummed upload path (`POST
    /import-sessions/{id}/source/upload`) instead. Raised as the very
    first step of the existing handler, before any CRUD call, so no
    database write is reachable — a metadata-only registration can never
    leave this dataset_type in a `registered` state with no durable blob
    behind it. Every other `dataset_type` is completely unaffected."""

    code = "IMPORT_SOURCE_REGISTRATION_METHOD_NOT_ALLOWED"
    status_code = 409


class ImportRecoveryRequiredError(DomainError):
    """Roadmap PR19A2 (design §9) — a mutating call hit a stale lease
    (pre-check: the session is `*_RUNNING` and its job's lease has already
    expired), or a completion write lost its own fencing check after the
    fact (post-check, §9.4.2 step 5). Never raised for a cleanly-recorded
    failure (§9.4.2 step 8) or for `TX2` infrastructure failure (§9.4.2
    step 7, which is a generic 500 instead)."""

    code = "IMPORT_RECOVERY_REQUIRED"
    status_code = 409


class ImportAttemptInProgressError(DomainError):
    """Roadmap PR19A2 (design §7, §17) — a concurrent request currently
    holds the running claim for this phase (the session is already
    `*_RUNNING` and its lease has not expired)."""

    code = "IMPORT_ATTEMPT_IN_PROGRESS"
    status_code = 409


class ImportAdapterNotRegisteredError(DomainError):
    """Roadmap PR19A2 (design §23) — no `ImportAdapter` is registered for
    this session's `dataset_type`. Production ships with an empty adapter
    registry (§26: no concrete parser in this foundation), so this is
    reachable for every real `dataset_type` until a future concrete-adapter
    slice registers one."""

    code = "IMPORT_ADAPTER_NOT_REGISTERED"
    status_code = 422


class ImportAdapterNotImplementedError(DomainError):
    """Roadmap PR19A3 (design §23) — an `ImportAdapter` is registered for
    this `dataset_type`, but does not override `plan_dry_run`/`execute`
    (§16/§17). Detected before admission (the adapter's method identity is
    compared against the base class's default, never by calling it and
    catching the resulting `NotImplementedError`), so a not-implemented
    adapter never enters `*_RUNNING` in the first place."""

    code = "IMPORT_ADAPTER_NOT_IMPLEMENTED"
    status_code = 501


class ImportExecutionFailedError(DomainError):
    """Roadmap PR19A3 (design §17, §21 endpoint #11, §23) — `execute`'s
    own runtime failure was cleanly recorded via a fenced `TX2` (§9.4.2
    step 8), the one phase where a completed-but-failed attempt is itself
    the HTTP error (`500`), unlike validate/dry-run's `200`. Never raised
    for a fencing loss (`409 IMPORT_RECOVERY_REQUIRED`) or a `TX2`
    infrastructure failure (the generic `500 INTERNAL_ERROR` envelope,
    §9.4.2 step 7) — only for the common case where `TX2` itself commits a
    genuine execution failure."""

    code = "IMPORT_EXECUTION_FAILED"
    status_code = 500


class ImportDryRunPlanNotFoundError(DomainError):
    """Roadmap PR20D (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md
    §14.6, §21) — no plan matches the requested lookup: either the session
    has never had a successful dry-run (`GET .../dry-run-plan`, no
    `active` plan exists), or the path `{plan_id}` does not reference a
    plan belonging to this session at all (`POST .../confirm`, ownership
    check). Never leaks a plan id belonging to a different session."""

    code = "IMPORT_DRY_RUN_PLAN_NOT_FOUND"
    status_code = 404


class ImportDryRunPlanStaleError(DomainError):
    """Roadmap PR20D (design §14.4a) — `POST .../dry-run-plan/{id}/confirm`
    matched zero rows: the plan is no longer `active` (superseded by a
    newer dry-run, or already `consumed`/`failed`), or the owning session
    has moved out of `dry_run_completed` (e.g. `cancelled`). The operator
    must re-fetch `GET .../dry-run-plan` and review the current plan
    before confirming again -- never silently retried against the same
    stale `plan_id`."""

    code = "IMPORT_DRY_RUN_PLAN_STALE"
    status_code = 409


class ImportNoConfirmedPlanError(DomainError):
    """Roadmap PR20E (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md
    §14.4a) -- raised by `precheck_execute`, before `admit_phase_job`
    runs, so no session state changes -- the session has no `active`
    plan with `confirmed_at IS NOT NULL`, either because the operator
    never confirmed a plan or because their confirmed plan has since
    been superseded by a newer, not-yet-confirmed dry-run. The operator
    must confirm the current plan (`POST .../dry-run-plan/{plan_id}/confirm`)
    before retrying `POST .../execute`."""

    code = "IMPORT_NO_CONFIRMED_PLAN"
    status_code = 409


class LegacyMigrationAuthorityNotFoundError(DomainError):
    """Roadmap PR21E0. No `LegacyMigrationAuthority` matches the requested
    lookup (by id, or by checksum) -- never leaks whether a checksum has
    ever been *seen* by the system (e.g. rejected during validation for a
    different reason), only whether an approved authority row exists for
    it."""

    code = "LEGACY_MIGRATION_AUTHORITY_NOT_FOUND"
    status_code = 404


class LegacyMigrationAuthorityScopeConflictError(DomainError):
    """Roadmap PR21E0 (design §5/§10) -- `POST /legacy-migration-authorities`
    was called with a checksum that is already approved under a
    *different* `scope`. `approved_workbook_sha256` is unique at the
    database level (one checksum, one governance identity) -- reusing an
    already-approved checksum under a different scope would silently
    reinterpret an existing governance decision, never permitted. The
    caller must use the checksum's existing scope, or approve a
    genuinely different workbook."""

    code = "LEGACY_MIGRATION_AUTHORITY_SCOPE_CONFLICT"
    status_code = 409


class ReconciliationRunNotFoundError(DomainError):
    """Roadmap PR22C (docs/design/PR22_LEGACY_DATA_RECONCILIATION_PLAN.md
    §11/§17.2) -- no `LegacyReconciliationRun` matches the requested id."""

    code = "RECONCILIATION_RUN_NOT_FOUND"
    status_code = 404


class ReconciliationRunNotPendingError(DomainError):
    """Roadmap PR22C -- `execute_reconciliation_run` was called for a run
    whose `status` is not `pending` (already `running`, `completed`, or
    `failed`). A completed/failed run is never re-executed (§27) -- the
    caller must create a new run instead."""

    code = "RECONCILIATION_RUN_NOT_PENDING"
    status_code = 409


class ReconciliationRunVersionConflictError(DomainError):
    """Roadmap PR22C (§8) -- the CAS claim (`WHERE id=:id AND
    status='pending' AND version=:expected_version`) matched zero rows:
    either a concurrent caller already claimed this run, or the caller's
    `expected_version` is stale. Exactly one concurrent claimant may ever
    win; every other claimant receives this error, never a duplicate
    execution."""

    code = "RECONCILIATION_RUN_VERSION_CONFLICT"
    status_code = 409


class UnsupportedReconciliationRuleVersionError(DomainError):
    """Roadmap PR22C (§4/§36) -- `run.rule_version` does not match the
    engine's own `PR22_RECONCILIATION_RULE_VERSION`. A run is bound to
    the rule version it was created for and never silently executed
    under a different engine version, and `run.rule_version` is never
    changed automatically -- fail closed instead."""

    code = "UNSUPPORTED_RECONCILIATION_RULE_VERSION"
    status_code = 422


class ReconciliationCoverageMismatchError(DomainError):
    """Roadmap PR22C (§38) -- the run's own copied
    `legacy_coverage_start`/`legacy_coverage_end`/`live_system_start`
    values do not exactly match its bound `LegacyMigrationAuthorityCoverage`
    artifact's current values, or `run.coverage_id` does not reference an
    existing coverage row at all. Never "repaired" -- the run is rejected
    and left untouched; there is no `MIN`/`MAX`-derived fallback."""

    code = "RECONCILIATION_COVERAGE_MISMATCH"
    status_code = 409


class ReconciliationAnalysisFailedError(DomainError):
    """Roadmap PR22C (§7/§26) -- the analysis transaction (projection +
    rule evaluation + finding persistence + completion) failed after the
    run was claimed. The run is transitioned `running -> failed` (fenced
    against a concurrent claimant, §7) in a separate transaction; no
    partial finding set is ever left visible for this run."""

    code = "RECONCILIATION_ANALYSIS_FAILED"
    status_code = 500


class ReconciliationFindingNotFoundError(DomainError):
    """Roadmap PR22D -- no `LegacyReconciliationFinding` row matches the
    given id. Used both for a standalone `GET .../legacy-reconciliation-
    findings/{finding_id}` lookup and for the disposition-mutation path's
    own existence check -- never distinguishes "never existed" from
    "exists under a different run" when a caller reaches a finding via a
    nested route, mirroring this repository's existing information-
    boundary discipline (see `app.crud.import_dry_run_plan.confirm_plan`'s
    collapsed missing/foreign-session handling)."""

    code = "RECONCILIATION_FINDING_NOT_FOUND"
    status_code = 404


class ReconciliationFindingVersionConflictError(DomainError):
    """Roadmap PR22D -- a disposition mutation's `expected_version` no
    longer matches the finding's current `version`. A concurrent
    Administrator already disposed (or re-disposed) this finding; the
    caller must re-fetch (`GET .../legacy-reconciliation-findings/
    {finding_id}`) and retry with the fresh version -- never blind-retry
    the same stale value."""

    code = "RECONCILIATION_FINDING_VERSION_CONFLICT"
    status_code = 409


class ReconciliationFindingRunNotCompletedError(DomainError):
    """Roadmap PR22D -- disposition mutation is only permitted while the
    finding's owning run has `status = 'completed'`. A `pending`/
    `running`/`failed` run has no stable, reviewable evidence yet (a
    `failed` run's partial state was never persisted at all, per PR22C
    §26's all-or-nothing guarantee) -- reviewing against it would mean
    reviewing evidence that may not exist yet or may still change under
    the reviewer."""

    code = "RECONCILIATION_FINDING_RUN_NOT_COMPLETED"
    status_code = 409


class ReconciliationFindingSignedOffError(DomainError):
    """Roadmap PR22D (§14-16 of the task) -- the finding's owning run
    already has a persisted `LegacyReconciliationSignOff` row. Once a run
    is signed off, every one of its findings' dispositions becomes
    permanently immutable. This is checked under the same
    `LegacyReconciliationRun` row lock (`SELECT ... FOR UPDATE`) acquired
    at the start of the disposition-mutation transaction, so a concurrent
    future PR22E sign-off creation can never race past an in-flight
    disposition mutation (or vice versa) -- see
    `app.crud.legacy_reconciliation.update_finding_disposition`'s own
    docstring for the full lock-order contract PR22E must also follow."""

    code = "RECONCILIATION_FINDING_SIGNED_OFF"
    status_code = 409
