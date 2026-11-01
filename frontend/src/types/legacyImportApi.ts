// Roadmap PR20F (Equipment Master Frontend Real API Integration) / PR21E
// (Legacy History Frontend Real Integration). Field-for-field mirror of the
// real backend schemas (backend/app/schemas/import_session.py,
// backend/app/schemas/legacy_history_import.py,
// backend/app/schemas/legacy_migration_authority.py), in the backend's own
// snake_case -- matching this codebase's existing convention for real API
// integrations (see services/equipment.ts, types/index.ts's
// Page<T>/TransactionOut). types/legacyImport.ts holds only the smaller,
// genuinely dataset-agnostic display types shared by both real workflows,
// in camelCase for presentational convenience -- never a mock/preview
// shape.
//
// This file has no mock/fixture counterpart: every shape here is real
// backend contract, consumed through services/equipmentMasterImportClient.ts
// and services/legacyHistoryImportClient.ts.

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

// Roadmap PR21E0/PR21E. Mirrors backend/app/schemas/legacy_migration_authority.py
// exactly. `scope` is a closed allowlist at the API layer
// (`LEGACY_MIGRATION_AUTHORITY_SCOPES`, currently exactly one value) -- the
// frontend never lets an operator type an arbitrary scope, only ever sends
// the one constant (services/legacyMigrationAuthorityClient.ts).
export type LegacyMigrationAuthorityScope = "pr21_legacy_transaction_history_v1";

export interface LegacyMigrationAuthorityOut {
  id: string;
  scope: string;
  approved_workbook_sha256: string;
  approved_by_user_id: string;
  approved_at: string;
  created_at: string;
}

// Roadmap PR21E0/PR21E. Mirrors backend/app/schemas/legacy_history_import.py
// exactly -- PR21's own insert-oriented (Issue/Receive event) plan shape,
// deliberately NOT a reuse of DryRunPlanSummaryOut/DryRunPlanOut/
// DryRunPlanRowOut above, which describe Equipment Master's own
// create/update/skip upsert shape (action, target_equipment_id,
// matched_identity_fields, expected_equipment_version -- none of which
// exist on this contract).
export interface LegacyHistoryDryRunPlanSummaryOut {
  total_rows: number;
  issue_events: number;
  receive_events: number;
  warnings: number;
  blocking_conflicts: number;
}

export interface LegacyHistoryDryRunPlanOut {
  id: string;
  import_session_id: string;
  import_source_id: string;
  migration_authority_id: string;
  status: string;
  is_current: boolean;
  created_at: string;
  confirmed_at: string | null;
  confirmed_by_user_id: string | null;
  summary: LegacyHistoryDryRunPlanSummaryOut;
}

export interface LegacyHistoryDryRunPlanSourceRefOut {
  sheet_name: string;
  source_row_number: number;
}

export interface LegacyHistoryDryRunPlanRowValuesOut {
  legacy_order_reference: string | null;
  equipment_id: string;
  occurred_at: string;
  legacy_ward_text: string | null;
  resolved_ward_id: string | null;
  legacy_bme_name: string | null;
  header_source_ref: LegacyHistoryDryRunPlanSourceRefOut;
  line_source_ref: LegacyHistoryDryRunPlanSourceRefOut;
}

export type LegacyHistoryEventType = "ISSUE" | "RECEIVE";

export interface LegacyHistoryDryRunPlanRowOut {
  id: string;
  source_row_number: number;
  event_type: LegacyHistoryEventType;
  legacy_source_row_key: string;
  // `null` only for a row whose plan artifact content has already been
  // redacted by retention -- never `null` for a live, unredacted row.
  values: LegacyHistoryDryRunPlanRowValuesOut | null;
  warnings: string[] | null;
}

export interface LegacyHistoryDryRunPlanConfirmOut {
  id: string;
  import_session_id: string;
  status: string;
  confirmed_at: string | null;
  confirmed_by_user_id: string | null;
  summary: LegacyHistoryDryRunPlanSummaryOut;
}
