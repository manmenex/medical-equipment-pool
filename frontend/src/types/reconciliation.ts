// Roadmap PR22F -- Reconciliation Frontend Integration. Explicit TS types
// mirroring backend/app/schemas/legacy_reconciliation.py's Pydantic
// contracts field-for-field, inspected at the exact PR22F baseline
// (896d92f8c00ee860c82892e4e4d466d5869dcf48) -- never guessed, never a
// mirror of the DB schema. The backend remains the sole source of
// business truth; these types only describe the wire shape.

export type ReconciliationRunStatus = "pending" | "running" | "completed" | "failed";
export type ReconciliationSeverity = "high" | "medium" | "low";

// OD-PR22-2's closed four-value vocabulary
// (backend/app/models/legacy_reconciliation.py's RECONCILIATION_DISPOSITIONS)
// -- no fifth value, and specifically never "confirmed_pair" (see PR22C
// §34 / PR22D §17-20). Widening this union is a backend contract change,
// never a frontend-only decision.
export type ReconciliationDisposition =
  | "confirmed_valid"
  | "confirmed_duplicate"
  | "accepted_unresolved"
  | "requires_correction";

// Finding `code` is a bounded, DB-unconstrained VARCHAR on the backend
// (PR22C owns the evolving taxonomy, see app/models/legacy_reconciliation.py's
// module docstring) -- deliberately kept as `string`, not a closed union,
// so a future backend-added code never breaks the frontend build. Known
// codes get a centralized Thai label with a safe fallback for anything
// else (see utils/reconciliationLabels.ts).
export type ReconciliationFindingCode = string;

export interface ReconciliationRunListItem {
  id: string;
  status: ReconciliationRunStatus;
  version: number;
  rule_version: string;
  snapshot_as_of: string;
  created_by_user_id: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  failed_at: string | null;
  legacy_coverage_start: string;
  legacy_coverage_end: string;
  live_system_start: string;
  summary_total_findings: number;
  summary_high: number;
  summary_medium: number;
  summary_low: number;
  has_signoff: boolean;
}

export interface ReconciliationRunDetail extends ReconciliationRunListItem {
  coverage_id: string;
  supersedes_run_id: string | null;
  // disposition value (or the literal "open" key for NULL/undispositioned)
  // -> count, exactly as returned by GET .../runs/{run_id}. Never derived
  // or recomputed on the frontend.
  finding_counts_by_disposition: Record<string, number>;
}

export interface ReconciliationFindingListItem {
  id: string;
  run_id: string;
  code: ReconciliationFindingCode;
  severity: ReconciliationSeverity;
  equipment_id: string | null;
  rule_version: string;
  disposition: ReconciliationDisposition | null;
  disposed_by_user_id: string | null;
  disposed_at: string | null;
  disposition_note: string | null;
  version: number;
  created_at: string;
}

export interface ReconciliationEquipmentSummary {
  id: string;
  asset_number: string;
  equipment_name: string;
  item_no: string | null;
  bcm_code: string | null;
  status: string;
}

export interface ReconciliationLegacyEventRef {
  id: string;
  event_type: string;
  occurred_at: string;
  legacy_source_row_key: string;
}

export interface ReconciliationFindingDetail extends ReconciliationFindingListItem {
  evidence: Record<string, unknown>;
  equipment: ReconciliationEquipmentSummary | null;
  events: ReconciliationLegacyEventRef[];
}

// PATCH /legacy-reconciliation-findings/{finding_id}/disposition request
// body. Deliberately only these three fields -- §17/§18 of the PR22D
// task: no generic update schema, `expected_version` must always be the
// exact `version` last read from the server, never guessed or
// incremented client-side.
export interface ReconciliationFindingDispositionRequest {
  disposition: ReconciliationDisposition;
  expected_version: number;
  disposition_note?: string | null;
}

// POST /legacy-reconciliation-runs/{run_id}/sign-off request body.
// Deliberately the *only* field ever sent -- the backend constructs the
// entire attestation from database truth (PR22E §8/§20-21 of the task).
// Never add attestation_summary/rule_version/coverage timestamps/finding
// counts/signer fields here.
export interface ReconciliationSignOffRequest {
  expected_version: number;
}

export interface ReconciliationSignOffDetail {
  id: string;
  run_id: string;
  signed_off_by_user_id: string;
  signed_off_at: string;
  attestation_summary: Record<string, unknown>;
  run_version_at_signoff: number;
}

// The public, stable backend error codes this PR's endpoints can return
// (docs/api/ERROR_CODES.md, PR22D/PR22E). Branch on these via
// apiErrorCode(), never on the free-text `detail` string.
export type ReconciliationFindingErrorCode =
  | "RECONCILIATION_RUN_NOT_FOUND"
  | "RECONCILIATION_FINDING_NOT_FOUND"
  | "RECONCILIATION_FINDING_VERSION_CONFLICT"
  | "RECONCILIATION_FINDING_RUN_NOT_COMPLETED"
  | "RECONCILIATION_FINDING_SIGNED_OFF";

export type ReconciliationSignOffErrorCode =
  | "RECONCILIATION_RUN_NOT_FOUND"
  | "RECONCILIATION_SIGNOFF_NOT_FOUND"
  | "RECONCILIATION_SIGNOFF_ALREADY_EXISTS"
  | "RECONCILIATION_SIGNOFF_RUN_NOT_COMPLETED"
  | "RECONCILIATION_SIGNOFF_VERSION_CONFLICT"
  | "RECONCILIATION_SIGNOFF_FINDINGS_INCOMPLETE"
  | "RECONCILIATION_SIGNOFF_REQUIRES_CORRECTION"
  | "RECONCILIATION_SIGNOFF_EVIDENCE_INCONSISTENT"
  | "RECONCILIATION_COVERAGE_MISMATCH";
