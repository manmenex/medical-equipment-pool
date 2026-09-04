import { api } from "@/services/api";
import type { BcmSuggestion, Equipment, EquipmentStatusHistoryItem, Page } from "@/types";

export interface EquipmentSearchParams {
  q?: string;
  status?: string;
  department_id?: string;
  category_id?: string;
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
  asset_number: string;
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
