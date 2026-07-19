// Roadmap PR6 (HOSPITAL_DOMAIN_MODEL.md): the confirmed 4-state model.
// legacy_status (pre-migration 8-state value) is deliberately not declared
// here -- historical/rollback metadata only, never read by the frontend.
export type EquipmentStatus =
  | "available_at_pool"
  | "issued_to_ward"
  | "unavailable_defective"
  | "decommissioned";

export type Role = "admin" | "biomedical_engineer" | "ward_nurse" | "transport_staff" | "viewer";

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

export interface TransactionOut {
  id: string;
  transaction_no: string;
  equipment: { id: string; asset_number: string; equipment_name: string; status: EquipmentStatus };
  quantity: number;
  borrowed_at: string;
  due_at: string | null;
  returned_at: string | null;
  borrower_name: string;
  ward_id: string | null;
  phone_number: string | null;
  condition_on_return: string | null;
  status: "borrowed" | "returned" | "overdue";
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
  pm_due_soon: number;
  cal_due_soon: number;
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
