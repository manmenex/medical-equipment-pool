// Roadmap PR20F (Equipment Master Frontend Real API Integration).
// Field-for-field mirror of backend/app/schemas/import_session.py, in the
// backend's own snake_case -- matching this codebase's existing convention
// for real API integrations (see services/equipment.ts, types/index.ts's
// Page<T>/TransactionOut), never the camelCase invented by the PR19B
// skeleton (types/legacyImport.ts, still used only by the Receive/Issue
// mock placeholders -- see services/legacyImportClient.ts).
//
// This file has no mock/fixture counterpart: every shape here is real
// backend contract, consumed only through services/equipmentMasterImportClient.ts.

// Matches backend/app/models/import_session.py's ck_import_sessions_status
// CHECK constraint exactly (11 values).
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

export interface ImportSessionOut {
  id: string;
  dataset_type: string;
  status: ImportSessionStatus;
  version: number;
  created_by_user_id: string;
  idempotency_key: string | null;
  notes: string | null;
  terminal_at: string | null;
  failure_reason: string | null;
  created_at: string;
  updated_at: string;
  validated_at: string | null;
  total_rows: number | null;
  valid_rows: number | null;
  invalid_rows: number | null;
  warning_rows: number | null;
  dry_run_completed_at: string | null;
  executed_at: string | null;
  imported_rows: number | null;
}

export interface ImportJobSummaryOut {
  id: string;
  job_type: string;
  status: string;
  attempt_number: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface ImportSessionSummaryOut extends ImportSessionOut {
  jobs: ImportJobSummaryOut[];
  finding_count: number;
  validation_attempt_id: string | null;
}

export interface ImportSourceOut {
  id: string;
  import_session_id: string;
  status: string;
  frozen_at: string | null;
  checksum: string;
  byte_size: number;
  content_type: string | null;
  filename: string | null;
  source_version: string | null;
  source_fingerprint: string;
  created_at: string;
}

export type ImportFindingSeverity = "error" | "warning";

export interface ValidationFindingOut {
  id: string;
  row_number: number | null;
  field: string | null;
  error_code: string;
  message: string;
  severity: ImportFindingSeverity;
}

// Roadmap PR20D (DryRunPlan). `action` is a plain string (matching this
// codebase's existing enum-as-CHECK-constrained-VARCHAR convention),
// always one of CREATE/UPDATE/SKIP -- never computed on the frontend.
export interface DryRunPlanRowOut {
  id: string;
  source_row_number: number;
  action: "CREATE" | "UPDATE" | "SKIP";
  target_equipment_id: string | null;
  normalized_values: Record<string, unknown> | null;
  matched_identity_fields: Record<string, unknown> | null;
  expected_equipment_version: number | null;
  warnings: Record<string, unknown>[] | null;
}

export interface DryRunPlanSummaryOut {
  total_rows: number;
  creates: number;
  updates: number;
  skips: number;
  warnings: number;
  blocking_conflicts: number;
}

export interface DryRunPlanOut {
  id: string;
  import_session_id: string;
  import_source_id: string;
  status: string;
  is_current: boolean;
  created_at: string;
  confirmed_at: string | null;
  confirmed_by_user_id: string | null;
  summary: DryRunPlanSummaryOut;
  rows: DryRunPlanRowOut[];
  rows_next_cursor: string | null;
  rows_total: number;
}

export interface DryRunPlanConfirmOut {
  id: string;
  import_session_id: string;
  status: string;
  confirmed_at: string | null;
  confirmed_by_user_id: string | null;
  summary: DryRunPlanSummaryOut;
}
