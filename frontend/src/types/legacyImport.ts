// Roadmap PR19B (Legacy Import Frontend Skeleton) -- frontend-only preview,
// reconciled against the now-merged PR19A1-A3 backend contract
// (docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md,
// backend/app/models/import_session.py, backend/app/schemas/
// import_session.py). PR19A is authoritative for every shape below that
// has a real backend field; this file must not diverge from it.
//
// This remains, nonetheless, a frontend-only, non-executing preview: no
// PR19B code path uploads a file, calls a real /import-sessions endpoint,
// or performs a real import -- see services/legacyImportClient.ts's
// MockImportClient, the only implementation this skeleton uses.
//
// Two things below are NOT covered by the merged PR19A contract, and
// remain this skeleton's own invention, clearly marked:
//  - `ImportCategory`'s three values (Equipment Master / Receive History /
//    Issue History) are PR20/PR21 preview labels pulled forward for
//    workflow review, not a backend `dataset_type` enum -- the real
//    column is free-text VARCHAR(100), unconstrained by any CHECK. See
//    docs/ROADMAP.md's PR19B scope note.
//  - The "dry-run result" screen: PR19A's `POST /{id}/dry-run` returns only
//    `ImportSessionOut` with `dry_run_completed_at` set -- no adapter/plan
//    response shape exists in this foundation (concrete adapters are
//    future PR20/PR21 scope, design §26 Non-Goals). This skeleton
//    therefore reuses the session's real validation counters for that
//    screen instead of inventing execute-outcome-shaped counts with no
//    contract to align to.

export type ImportCategory = "equipment_master" | "receive_history" | "issue_history";

// Matches backend/app/models/import_session.py's `ck_import_sessions_status`
// CHECK constraint exactly (11 values) -- not a frontend invention. Do not
// add a status value here that does not also exist in that constraint.
export type ImportSessionStatus =
  | "created"
  | "validating"
  | "validated"
  | "validation_failed"
  | "dry_run_running"
  | "dry_run_completed"
  | "dry_run_failed"
  | "executing"
  | "completed"
  | "failed"
  | "cancelled";

// Matches backend/app/models/import_session.py's
// `ck_import_row_errors_severity` CHECK constraint. Per design §24 rule 10,
// a WARNING never blocks progress -- UI must never imply otherwise.
export type ImportFindingSeverity = "error" | "warning";

// Matches backend/app/schemas/import_session.py's `ValidationFindingOut`
// field-for-field (id/row_number/field/error_code/message/severity).
// `submittedValue` from the pre-reconciliation skeleton had no backend
// counterpart and has been removed.
export interface ImportFinding {
  id: string;
  rowNumber: number | null;
  field: string | null;
  errorCode: string;
  message: string;
  severity: ImportFindingSeverity;
}

// Matches backend/app/schemas/import_session.py's `ImportSessionOut`
// field-for-field where a real field exists. `skippedCount`/`failedCount`
// from the pre-reconciliation skeleton had no backend counterpart (only
// `imported_rows` exists at session level) and have been removed.
export interface ImportSessionSummary {
  id: string;
  datasetType: ImportCategory;
  status: ImportSessionStatus;
  createdByUserId: string;
  // Mock-only display convenience. The real `ImportSessionOut` has no
  // display-name field, only `created_by_user_id` (a user id reference) --
  // no name-resolution endpoint exists in this foundation to resolve one
  // for real. Kept here as clearly-mock UI sugar only.
  requestedByDisplayName: string;
  createdAt: string;
  totalRows: number | null;
  validRows: number | null;
  invalidRows: number | null;
  warningRows: number | null;
  importedRows: number | null;
  // Matches `ImportSessionOut.failure_reason` (backend/app/schemas/
  // import_session.py) -- a bounded, generic operator-facing message set
  // only when a phase's fenced *crash-recovery* write records a failure
  // (design §9.4.2), e.g. "recovered: prior attempt abandoned after lease
  // expiry" or an adapter's bounded error text. Distinct from a clean
  // `VALIDATION_FAILED` completion that simply found blocking row errors
  // (design §9.4.1/§13's success path) -- that outcome is communicated
  // entirely by `findings`/the row counters, never by this field. Always
  // non-null for `dry_run_failed`/`failed` (design §16/§9.4.2 -- neither
  // has a "clean, found issues" variant the way validate does); null for
  // every other status, including a clean `validation_failed`.
  failureReason: string | null;
  // Mock-only, combined-view convenience: in the real contract `filename`
  // belongs to the separate `ImportSource` resource (registered via
  // `POST /{id}/source`), not to `ImportSession` itself.
  filename: string;
}

// Mirrors the four real counters on `ImportSessionOut`
// (total_rows/valid_rows/invalid_rows/warning_rows). No `duplicateRows`
// field -- the real contract has no such counter; a duplicate row is
// represented as one specific `errorCode` on an `ImportFinding` instead.
export interface ImportValidationCounts {
  totalRows: number;
  validRows: number;
  warningRows: number;
  invalidRows: number;
}

// Presentational-only grouping of mock findings by Thai label for display
// -- not a real backend aggregate (no such endpoint exists in this
// foundation); derived from `findings`, never authoritative on its own.
export interface ImportFindingCategoryCount {
  categoryLabelTh: string;
  count: number;
}

// Mirrors what actually exists on `ImportSessionOut` once execute
// completes: `status`, `imported_rows`, `terminal_at`, and the session's
// own `id`. `skippedCount`/`failedCount` had no backend counterpart and
// have been removed.
//
// `importedRows` is nullable like the real `imported_rows` field: a
// FAILED execution rolls back every domain write it attempted (design
// §19), and a CANCELLED session never reaches execute at all (design
// §5's transition table only allows cancel from {CREATED, VALIDATED,
// VALIDATION_FAILED, DRY_RUN_COMPLETED, DRY_RUN_FAILED}) -- neither has a
// real "rows imported" outcome, so both must render as null, never a
// coerced 0. Only a COMPLETED session ever reports a real, non-null count.
export interface ImportResultSummary {
  status: Extract<ImportSessionStatus, "completed" | "failed" | "cancelled">;
  importedRows: number | null;
  terminalAt: string | null;
  sessionId: string;
}

export interface ImportSessionDetail extends ImportSessionSummary {
  requestedFileSizeBytes: number;
  validationCounts: ImportValidationCounts | null;
  findingsByCategory: ImportFindingCategoryCount[];
  findings: ImportFinding[];
  resultSummary: ImportResultSummary | null;
}

// The local, never-uploaded description of a selected browser File object --
// name/size/type only, per PR19B's "no real file processing" scope
// boundary. The File itself is never held past the component that read it.
export interface SelectedFilePreview {
  name: string;
  sizeBytes: number;
  type: string;
}

// Mirrors backend/app/schemas/common.py's `Page[T]` shape exactly
// (items/next_cursor/total) -- `GET /import-sessions` is cursor-paginated
// in the real contract, even though this skeleton's mock client never
// needs a second page for its fixed fixture set.
export interface ImportSessionPage {
  items: ImportSessionSummary[];
  nextCursor: string | null;
  total: number;
}
