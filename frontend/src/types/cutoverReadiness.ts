// Roadmap PR23E -- Cutover Readiness Frontend / Operator Workflow. Explicit
// TS types mirroring backend/app/schemas/cutover_readiness.py's Pydantic
// contracts field-for-field, inspected at the exact PR23E baseline
// (2da80231d4f037136b291863e379e739aa2905dd) -- never guessed, never a
// mirror of the DB schema. The backend remains the sole source of business
// truth; these types only describe the wire shape.

export type CutoverRunStatus = "pending" | "running" | "completed" | "failed";
export type CutoverSourceOfTruthStrategy = "hard_cutover";

export interface CutoverReadinessRunListItem {
  id: string;
  status: CutoverRunStatus;
  version: number;
  created_by_user_id: string;
  created_at: string;
  completed_at: string | null;
  completed_by_user_id: string | null;
  application_baseline_sha: string;
  database_migration_head: string;
  source_of_truth_strategy: CutoverSourceOfTruthStrategy;
  cutover_instant: string;
  freeze_window_reference: string | null;
  supersedes_run_id: string | null;
}

export interface CutoverReadinessRunDetail extends CutoverReadinessRunListItem {
  equipment_master_import_source_id: string | null;
  legacy_migration_authority_id: string | null;
  legacy_coverage_id: string | null;
  reconciliation_run_id: string | null;
  reconciliation_signoff_id: string | null;
  current_state_verified_at: string | null;
  current_state_verified_by_user_id: string | null;
  current_state_verification_scope_count: number | null;
  current_state_verification_reference: string | null;
  pilot_ward_id: string | null;
  operational_approver_reference: string | null;
}

// design §12/§13 -- Gate G (cutover authorization) is deliberately absent
// from this closed set; it is PR23D's own Go/No-Go decision, never a
// gate-evaluation "gate" itself.
export type CutoverGateCode = "A" | "B" | "C" | "D" | "E" | "F";
export type CutoverGateItemCategory = "blocker" | "warning" | "info";
export type CutoverGateStatus = "blocker" | "warning" | "satisfied";

export interface CutoverGateEvaluationItem {
  gate: CutoverGateCode;
  category: CutoverGateItemCategory;
  // Bounded but evolvable (mirrors ReconciliationFindingCode's own
  // precedent) -- a future backend-added code must never break the
  // frontend build. Known codes get a centralized Thai label with a safe
  // fallback; see utils/cutoverReadinessLabels.ts.
  code: string;
  message: string;
  manual_attestation_required: boolean;
  detail: Record<string, unknown>;
}

export interface CutoverGateSummary {
  gate: CutoverGateCode;
  mandatory: boolean;
  status: CutoverGateStatus;
}

export interface CutoverGateEvaluationResponse {
  cutover_readiness_run_id: string;
  evaluated_at: string;
  has_blocker: boolean;
  gates: CutoverGateSummary[];
  items: CutoverGateEvaluationItem[];
}

// Roadmap PR23D -- Go/No-Go Decision (Gate G). A different domain than
// CutoverGateItemCategory above -- this is the final decision *value*,
// never an Equipment lifecycle state.
export type CutoverGoNoGoDecisionValue = "GO" | "NO_GO";

// POST .../decision request body. Deliberately only these four fields --
// `acknowledged_warning_codes` must be drawn exclusively from the current
// GET .../gate-evaluation response's own live warning codes, never
// arbitrary user-typed text (§6/§23 of the task). `expected_version` must
// always be the exact `version` last read from GET .../{run_id}, never
// guessed or incremented client-side.
export interface CutoverDecisionCreateRequest {
  expected_version: number;
  decision: CutoverGoNoGoDecisionValue;
  acknowledged_warning_codes: string[];
  no_go_reason?: string | null;
}

export interface CutoverDecisionDetail {
  id: string;
  cutover_readiness_run_id: string;
  decision: CutoverGoNoGoDecisionValue;
  recorded_by_user_id: string;
  recorded_at: string;
  run_version_at_decision: number;
  acknowledged_warning_codes: string[];
  no_go_reason: string | null;
}

// The public, stable backend error codes this PR's endpoints can return
// (docs/api/ERROR_CODES.md, PR23B/C/D). Branch on these via apiErrorCode(),
// never on the free-text `detail` string.
export type CutoverReadinessErrorCode =
  | "CUTOVER_READINESS_RUN_NOT_FOUND"
  | "CUTOVER_READINESS_GATE_EVALUATION_REQUIRES_COMPLETED_RUN"
  | "CUTOVER_DECISION_NOT_FOUND"
  | "CUTOVER_DECISION_REQUIRES_COMPLETED_RUN"
  | "CUTOVER_DECISION_RUN_SUPERSEDED"
  | "CUTOVER_DECISION_STALE_VERSION"
  | "CUTOVER_DECISION_ALREADY_EXISTS"
  | "CUTOVER_DECISION_BLOCKED_BY_READINESS"
  | "CUTOVER_DECISION_WARNINGS_NOT_ACKNOWLEDGED";
