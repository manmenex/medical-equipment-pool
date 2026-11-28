import { api } from "@/services/api";
import type {
  BcmSuggestion,
  ChecklistKind,
  Equipment,
  EquipmentSource,
  EquipmentStatus,
  EquipmentStatusHistoryItem,
  Page,
} from "@/types";

// Roadmap PR31/PR28: read-only scan-time pre-check (status warning + checklist kind).
export interface DispatchCheck {
  equipment_id: string;
  status: EquipmentStatus;
  warning: "already_dispatched" | "defective" | "decommissioned" | "returned_to_owner" | null;
  dispatchable: boolean;
  requires_acknowledgement: boolean;
  current_ward_id: string | null;
  current_ward_name: string | null;
  dispatched_at: string | null;
  open_transaction_id: string | null;
  open_transaction_no: string | null;
  checklist_kind: ChecklistKind;
  // Roadmap PR33 (D14)
  equipment_source?: EquipmentSource;
  owner_company?: string | null;
  due_back_date?: string | null;
  has_charger?: boolean;
  has_clamp?: boolean;
  returned_to_owner_at?: string | null;
}

export async function getDispatchCheck(id: string): Promise<DispatchCheck> {
  return (await api.get<DispatchCheck>(`/equipment/${id}/dispatch-check`)).data;
}

export interface EquipmentSearchParams {
  q?: string;
  status?: string;
  department_id?: string;
  category_id?: string;
  // Roadmap PR33 (D14): source filter; returned-to-owner devices are hidden
  // unless include_returned is set (equipment management).
  source?: EquipmentSource;
  include_returned?: boolean;
  limit?: number;
  cursor?: string | null;
}

export async function searchEquipment(params: EquipmentSearchParams): Promise<Page<Equipment>> {
  const resp = await api.get<Page<Equipment>>("/equipment", { params });
  return resp.data;
}

export async function getEquipment(id: string): Promise<Equipment> {
  const resp = await api.get<Equipment>(`/equipment/${id}`);
  return resp.data;
}

// QR resolver (See ADR-004): scan existing hospital QR -> extract Item No
// (server-side) -> internal Equipment Master lookup. A POST with the raw
// scanned text in the body, not a GET path segment, so an arbitrary QR
// payload never lands in a URL/access log.
export async function resolveEquipmentByQr(rawValue: string): Promise<Equipment> {
  const resp = await api.post<Equipment>("/equipment/resolve-qr", { raw_value: rawValue });
  return resp.data;
}

// Roadmap PR5 fallback workflow: BCM-Code-only manual search suggestions.
// Response is intentionally minimal -- id + bcm_code only.
export async function searchBcmSuggestions(q: string, limit = 10): Promise<BcmSuggestion[]> {
  if (!q.trim()) return [];
  const resp = await api.get<BcmSuggestion[]>("/equipment/search/bcm", { params: { q, limit } });
  return resp.data;
}

export async function getEquipmentHistory(id: string): Promise<EquipmentStatusHistoryItem[]> {
  const resp = await api.get<EquipmentStatusHistoryItem[]>(`/equipment/${id}/history`);
  return resp.data;
}

export interface EquipmentCreatePayload {
  asset_number?: string;
  equipment_name: string;
  serial_number?: string;
  category_id?: string;
  brand?: string;
  model?: string;
  department_owner_id?: string;
  current_location_id?: string;
  // item_no is deliberately omitted here -- no admin UI in this PR
  // manually assigns it; its intended source is a future controlled
  // Excel import (Roadmap PR12).
  bcm_code?: string;
}

export async function createEquipment(payload: EquipmentCreatePayload): Promise<Equipment> {
  const resp = await api.post<Equipment>("/equipment", payload);
  return resp.data;
}

export async function updateEquipment(id: string, payload: Partial<EquipmentCreatePayload>): Promise<Equipment> {
  const resp = await api.patch<Equipment>(`/equipment/${id}`, payload);
  return resp.data;
}

export async function changeEquipmentStatus(id: string, status: string, reason?: string): Promise<Equipment> {
  const resp = await api.post<Equipment>(`/equipment/${id}/status`, { status, reason });
  return resp.data;
}

// Roadmap PR33 (D14) "คืนผู้ให้ยืม": administrator-only; only a demo/loan
// device that is available at the pool.
export async function returnToOwner(id: string): Promise<Equipment> {
  const resp = await api.post<Equipment>(`/equipment/${id}/return-to-owner`);
  return resp.data;
}

export interface DemoLoanShared {
  category_id: string;
  brand?: string;
  model?: string;
  equipment_source: "demo" | "loan";
  owner_company: string;
  due_back_date?: string;
}

export interface DemoLoanItemInput {
  serial_number: string;
  has_charger: boolean;
  has_clamp: boolean;
}

export type DemoLoanRowError = "blank" | "invalid_serial" | "duplicate_in_batch" | "duplicate_in_db";

export interface DemoLoanRowResult {
  index: number;
  serial_number: string;
  errors: DemoLoanRowError[];
  messages: string[];
}

export interface DemoLoanBatchResult {
  dry_run: boolean;
  valid: boolean;
  committed: boolean;
  total: number;
  created_count: number;
  rows: DemoLoanRowResult[];
  created: Equipment[];
}

// dry_run=true validates only (nothing is written); otherwise the batch is
// committed all-or-nothing.
export async function registerDemoLoanBatch(body: {
  shared: DemoLoanShared;
  items: DemoLoanItemInput[];
  dry_run: boolean;
}): Promise<DemoLoanBatchResult> {
  const resp = await api.post<DemoLoanBatchResult>("/equipment/demo-loan-batch", body);
  return resp.data;
}
