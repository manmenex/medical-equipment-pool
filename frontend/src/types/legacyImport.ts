// Roadmap PR20F (Equipment Master Frontend Real API Integration) / PR21E
// (Legacy History Frontend Real Integration). Shared, dataset-agnostic
// display types used by both real workflows -- every shape below is a
// genuine 1:1 mirror of a real backend field (see the per-field comments),
// reconciled against the merged PR19A/PR20/PR21E0 backend contracts
// (backend/app/models/import_session.py, backend/app/schemas/
// import_session.py). Neither workflow may diverge from it.
//
// The former PR19B mock skeleton (MockImportClient, legacyImportFixtures.ts,
// the "receive_history"/"issue_history" separate preview categories, and
// every mock-only container type that used to live in this file --
// ImportSessionSummary/ImportSessionDetail/ImportSessionPage/
// SelectedFilePreview) has been removed: both import categories now go
// through the real backend (services/equipmentMasterImportClient.ts,
// services/legacyHistoryImportClient.ts), never a frontend-only preview.

// PR21E (design §2): PR21 V1 is one combined Issue+Receive workflow, not
// two separate Receive/Issue History categories -- see docs/design/
// PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md. The real `dataset_type`
// column is free-text VARCHAR(100), unconstrained by any CHECK; these two
// values are this frontend's own closed set of real, backend-integrated
// categories, matching services/equipmentMasterImportClient.ts's
// EQUIPMENT_MASTER_DATASET_TYPE and
// services/legacyHistoryImportClient.ts's LEGACY_TRANSACTION_HISTORY_DATASET_TYPE
// exactly.
export type ImportCategory = "equipment_master" | "legacy_transaction_history";

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
// `ck_import_row_errors_severity` CHECK constraint. A WARNING never blocks
// progress -- UI must never imply otherwise.
export type ImportFindingSeverity = "error" | "warning";

// Matches backend/app/schemas/import_session.py's `ValidationFindingOut`
// field-for-field (id/row_number/field/error_code/message/severity).
export interface ImportFinding {
  id: string;
  rowNumber: number | null;
  field: string | null;
  errorCode: string;
  message: string;
  severity: ImportFindingSeverity;
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

// Presentational-only grouping of findings by label for display -- not a
// real backend aggregate (no such endpoint exists in either contract);
// derived from `findings` by a caller, never authoritative on its own.
export interface ImportFindingCategoryCount {
  categoryLabelTh: string;
  count: number;
}

// Mirrors what actually exists on `ImportSessionOut` once execute
// completes: `status`, `imported_rows`, `terminal_at`, and the session's
// own `id`.
//
// `importedRows` is nullable like the real `imported_rows` field: a FAILED
// execution rolls back every domain write it attempted, and a CANCELLED
// session never reaches execute at all -- neither has a real "rows
// imported" outcome, so both render as null, never a coerced 0. Only a
// COMPLETED session ever reports a real, non-null count.
export interface ImportResultSummary {
  status: Extract<ImportSessionStatus, "completed" | "failed" | "cancelled">;
  importedRows: number | null;
  terminalAt: string | null;
  sessionId: string;
}
