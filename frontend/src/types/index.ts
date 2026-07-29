// Roadmap PR6 (HOSPITAL_DOMAIN_MODEL.md): the confirmed 4-state model.
// legacy_status (pre-migration 8-state value) is deliberately not declared
// here -- historical/rollback metadata only, never read by the frontend.
export type EquipmentStatus =
  | "available_at_pool"
  | "issued_to_ward"
  | "unavailable_defective"
  | "decommissioned";

// Roadmap PR10 (Role Model Consolidation): the confirmed 3-role model,
// replacing the legacy 5-role set (admin, biomedical_engineer, ward_nurse,
// transport_staff, viewer). See backend/app/models/user.py's ALL_ROLES for
// the single backend source of truth this type mirrors.
export type Role = "administrator" | "equipment_pool_staff" | "read_only";

export interface UserProfile {
  id: string;
  employee_code: string;
  full_name: string;
  email: string;
  role: Role;
  permissions: Record<string, unknown>;
}

export interface Equipment {
  id: string;
  asset_number: string;
  serial_number: string | null;
  equipment_name: string;
  category_id: string | null;
  brand: string | null;
  model: string | null;
  department_owner_id: string | null;
  current_location_id: string | null;
  status: EquipmentStatus;
  // bcm_code is the operator-facing identifier (display only here, See
  // ADR-003). item_no and qr_code_value are deliberately NOT declared on
  // this type -- item_no is an internal QR-resolution key the frontend
  // never reads or renders (See ADR-002), and the backend no longer
  // returns either in an operator-facing response.
  bcm_code: string | null;
  pm_due_date: string | null;
  cal_due_date: string | null;
  created_at: string;
  updated_at: string;
}

// Roadmap PR5: the minimum data the BCM manual-search suggestion list
// needs to display a result and let the operator select it. Deliberately
// excludes item_no and every other equipment field.
export interface BcmSuggestion {
  id: string;
  bcm_code: string;
}

export interface EquipmentStatusHistoryItem {
  id: string;
  from_status: string | null;
  to_status: string;
  reason: string | null;
  changed_at: string;
}

// Roadmap PR7b: exactly two dispatch types, and the confirmed fixed
// four-round MVP schedule (docs/audits/04-consolidated-implementation-plan.md
// confirmed-requirements table). Do not add a named label for a round --
// none is confirmed; the value is the literal clock time itself.
export type DispatchType = "routine_round" | "on_demand";
export type RoutineRound = "06:00" | "11:00" | "15:00" | "21:00";

// Roadmap PR16 (docs/design/PR16_REPORTING_FOUNDATION_PLAN.md §7/§8):
// mirrors the backend's `app.core.reporting_time.Shift` enum exactly --
// `business_date`/`shift` are always backend-computed (never invented or
// recalculated here); the frontend only ever sends/displays these two
// values verbatim.
export type Shift = "day" | "night";

// The closed, two-value `event` basis GET /transactions filters against
// (Roadmap PR16 Slice 3, §8): `dispatch` reads `borrowed_at`-derived
// fields, `receipt` reads `returned_at`-derived fields. Matches the
// backend's `Literal["dispatch", "receipt"]` exactly -- do not widen.
export type TransactionEventBasis = "dispatch" | "receipt";

// Roadmap PR8B (backend/app/models/transaction.py's ReceiptOutcome,
// knowledge/adr/ADR-006-receipt-outcome-contract.md): the confirmed binary
// receipt outcome -- the exact domain vocabulary
// docs/HOSPITAL_DOMAIN_MODEL.md's "Confirmed workflow" uses ("receipt
// outcome: usable" / "receipt outcome: defective"). This is a union, not a
// generic `string` -- do not widen it. The backend alone maps this value
// to an equipment lifecycle state (EquipmentStatus); the frontend must
// never submit a lifecycle state directly.
export type ReceiptOutcome = "usable" | "defective";

export interface TransactionOut {
  id: string;
  transaction_no: string;
  equipment: { id: string; asset_number: string; equipment_name: string; status: EquipmentStatus };
  quantity: number;
  borrowed_at: string;
  // Roadmap PR7b: due_at is deliberately absent -- removed from the active
  // request/response contract (ADR-005 decision 3 already retired the
  // due-date/overdue workflow).
  returned_at: string | null;
  // Nullable going forward (Roadmap PR7b) -- no longer required or
  // accepted on dispatch; a pre-existing transaction may still have one.
  borrower_name: string | null;
  ward_id: string | null;
  dispatch_type: DispatchType | null;
  routine_round: RoutineRound | null;
  phone_number: string | null;
  // Roadmap PR8B: replaces condition_on_return. Strictly ReceiptOutcome |
  // null -- never one of the pre-PR8B legacy values (available/pm/
  // calibration/repair). Null both for a transaction not yet received and
  // for one received before this contract existed; see
  // legacy_condition_on_return below for that case.
  receipt_outcome: ReceiptOutcome | null;
  // Roadmap PR8B: a pre-PR8B transaction's original recorded value
  // (available/pm/calibration/repair), preserved verbatim, read-only.
  // Mutually exclusive with receipt_outcome -- never both non-null for the
  // same transaction. Never rendered as if it were a current-contract
  // outcome.
  legacy_condition_on_return: string | null;
  status: "open" | "closed";
  notes: string | null;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
  total: number;
}

export interface DashboardSummary {
  total: number;
  available_at_pool: number;
  issued_to_ward: number;
  unavailable_defective: number;
  decommissioned: number;
}

export interface BorrowTrendPoint {
  date: string;
  count: number;
}

export interface TopBorrowedItem {
  equipment_id: string;
  asset_number: string;
  equipment_name: string;
  borrow_count: number;
}

export interface Department {
  id: string;
  code: string;
  name: string;
}

export interface Ward {
  id: string;
  code: string;
  name: string;
  department_id: string | null;
}

export interface Location {
  id: string;
  name: string;
  type: string | null;
}

export interface Category {
  id: string;
  name: string;
  default_pm_interval_days: number | null;
  default_cal_interval_days: number | null;
}

export interface ApiError {
  detail: string;
  code: string;
  status: number;
}

// Roadmap PR9B (backend/app/schemas/transaction.py's WardCorrectionRequest):
// exactly the merged PR9A request contract -- ward_id and a mandatory
// reason, nothing else. The response is the existing TransactionOut above,
// reused as-is (see docs/api/transactions.md).
export interface WardCorrectionPayload {
  ward_id: string;
  reason: string;
}

// The stable, machine-readable `code` values this action's endpoint
// (POST /transactions/{id}/correct-ward) can return, per docs/api/
// ERROR_CODES.md and docs/api/transactions.md. Branch on this, never on
// the free-text `detail` (same convention Roadmap PR8C established for
// receipt errors -- see services/api.ts's apiErrorCode).
export type WardCorrectionErrorCode =
  | "FORBIDDEN"
  | "TRANSACTION_NOT_FOUND"
  | "INVALID_INPUT"
  | "WARD_CORRECTION_NOOP"
  | "WARD_CORRECTION_CONFLICT"
  | "VALIDATION_ERROR";

// Roadmap PR12 (Inventory Import, backend/app/services/import_service.py):
// per-row outcome of a parsed spreadsheet row. "skipped" is distinct from
// "failed" -- a skip means the row's BCM Code already exists in the
// database and update mode was off (not a data-quality problem with the
// row itself).
export type ImportRowStatus = "success" | "failed" | "skipped";

// Present only for a "success" row. Roadmap PR12 is update-only (see the
// backend module docstring): every successful row is an update to an
// existing equipment record matched by BCM Code -- import never creates
// new equipment.
export type ImportRowAction = "update";

export interface ImportRowResult {
  row_number: number;
  bcm_code: string | null;
  item_no: string | null;
  asset_id: string | null;
  status: ImportRowStatus;
  action: ImportRowAction | null;
  reason: string | null;
  equipment_id: string | null;
}

export interface ImportPreviewResponse {
  filename: string;
  total_rows: number;
  succeeded: number;
  failed: number;
  skipped: number;
  rows: ImportRowResult[];
}

// Roadmap PR12: `audit_log_id` is the one batch-level audit entry recorded
// for a commit -- never one entry per row.
export interface ImportCommitResponse extends ImportPreviewResponse {
  audit_log_id: string | null;
}
