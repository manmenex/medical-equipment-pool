import { api } from "@/services/api";
import type { Equipment, EquipmentStatusHistoryItem, Page } from "@/types";

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

export async function getEquipmentByQr(qrValue: string): Promise<Equipment> {
  const resp = await api.get<Equipment>(`/equipment/by-qr/${encodeURIComponent(qrValue)}`);
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

export function equipmentQrCodeUrl(id: string): string {
  return `/api/v1/equipment/${id}/qrcode`;
}
