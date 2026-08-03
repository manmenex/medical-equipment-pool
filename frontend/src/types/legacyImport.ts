// Roadmap PR19B (Legacy Import Frontend Skeleton) -- PROVISIONAL, FRONTEND-
// ONLY PREVIEW CONTRACTS.
//
// No PR19 design document exists in docs/design/ yet, and no PR19A backend
// branch/PR/schema exists at the time this skeleton was built (verified
// against docs/ROADMAP.md, docs/ROADMAP_STATUS.md, and
// docs/audits/04-consolidated-implementation-plan.md Part D, Group 8).
// Everything in this file is this skeleton's own invention for review
// purposes only -- it is NOT an approved backend API contract, must not be
// imported by any non-PR19B code, and must be realigned (or replaced
// outright) once PR19A's real public API contract is approved and merged.
//
// Deliberately kept out of the shared frontend/src/types/index.ts so it can
// never be mistaken for an established, cross-cutting type the rest of the
// app already relies on.
//
// Scope note: docs/audits/04-consolidated-implementation-plan.md Group 8
// defines PR19 itself as "a staged, validation-first, traceable import
// framework" only -- the three ImportCategory values below (Equipment
// Master / Receive History / Issue History) are actually PR20 and PR21
// scope, each with PR19 as a listed dependency. Including them in this
// PR19B skeleton is a deliberate, Repository-Owner-confirmed scope
// decision to preview the end-to-end workflow, not a claim that PR20/PR21
// are approved or implemented. See the PR description for the full
// decision trail.

export type ImportCategory = "equipment_master" | "receive_history" | "issue_history";

// PROVISIONAL. Not a confirmed backend state machine -- invented here only
// to demonstrate the reviewable screen states the user-goal workflow
// (session list -> create -> file -> validate -> dry run -> confirm ->
// result) needs. A real PR19A contract may use different names, a
// different set of states, or a different transition shape entirely.
export type ImportSessionStatus =
  | "uploaded"
  | "validating"
  | "validated"
  | "dry_run_completed"
  | "awaiting_confirmation"
  | "completed"
  | "completed_with_warnings"
  | "failed"
  | "cancelled";

export interface ImportSessionSummary {
  id: string;
  importCategory: ImportCategory;
  filename: string;
  status: ImportSessionStatus;
  requestedByDisplayName: string;
  createdAt: string;
  totalRows: number | null;
  importedCount: number | null;
  skippedCount: number | null;
  failedCount: number | null;
}

export interface ImportValidationCategoryCount {
  categoryLabelTh: string;
  count: number;
}

export interface ImportValidationSummary {
  totalRows: number;
  validRows: number;
  warningRows: number;
  invalidRows: number;
  duplicateRows: number;
  byCategory: ImportValidationCategoryCount[];
}

export type ImportIssueSeverity = "error" | "warning";

export interface ImportIssue {
  rowNumber: number;
  field: string;
  submittedValue: string;
  issueCode: string;
  explanationTh: string;
  severity: ImportIssueSeverity;
}

export interface ImportDryRunSummary {
  wouldCreateCount: number;
  wouldSkipCount: number;
  duplicateCount: number;
  validationFailureCount: number;
  warningCount: number;
}

export type ImportResultStatus = Extract<
  ImportSessionStatus,
  "completed" | "completed_with_warnings" | "failed" | "cancelled"
>;

export interface ImportResultSummary {
  status: ImportResultStatus;
  importedCount: number;
  skippedCount: number;
  failedCount: number;
  completedAt: string | null;
  sessionReference: string;
}

export interface ImportSessionDetail extends ImportSessionSummary {
  requestedFileSizeBytes: number;
  validationSummary: ImportValidationSummary | null;
  issues: ImportIssue[];
  dryRunSummary: ImportDryRunSummary | null;
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
