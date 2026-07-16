export type EquipmentStatus =
  | "available"
  | "borrowed"
  | "cleaning"
  | "pm"
  | "calibration"
  | "repair"
  | "out_of_service"
  | "lost";

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
  qr_code_value: string;
  pm_due_date: string | null;
  cal_due_date: string | null;
  created_at: string;
  updated_at: string;
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
  available: number;
  borrowed: number;
  cleaning: number;
  pm: number;
  calibration: number;
  repair: number;
  out_of_service: number;
  lost: number;
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
