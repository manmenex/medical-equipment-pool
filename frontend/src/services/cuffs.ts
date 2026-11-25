import { api } from "@/services/api";
import type { Cuffs } from "@/types";

// Roadmap PR28 (D11): outstanding Cryo-Cuff tracking (docs/api/ward-first-entry.md section 4).
export interface OutstandingCuffTx {
  transaction_id: string;
  transaction_no: string;
  equipment_id: string;
  bcm_code: string | null;
  equipment_name: string;
  dispatched_at: string;
  device_received: boolean;
  cuffs: Cuffs;
}

export interface OutstandingCuffWard {
  ward_id: string | null;
  ward_name: string | null;
  cuffs: Cuffs;
  total: number;
  transactions: OutstandingCuffTx[];
}

export interface OutstandingCuffs {
  total_outstanding: number;
  items: OutstandingCuffWard[];
}

export async function getOutstandingCuffs(wardId?: string): Promise<OutstandingCuffs> {
  const resp = await api.get<OutstandingCuffs>("/cuffs/outstanding", { params: wardId ? { ward_id: wardId } : {} });
  return resp.data;
}

export interface ReceiveCuffsResult {
  transaction_id: string;
  transaction_no: string;
  cuffs_issued: Cuffs;
  cuffs_returned: Cuffs;
  cuffs_outstanding: Cuffs;
}

export async function receiveCuffs(
  transactionId: string,
  cuffs: Partial<Cuffs>,
  wardContactName?: string | null,
): Promise<ReceiveCuffsResult> {
  const resp = await api.post<ReceiveCuffsResult>(`/transactions/${transactionId}/receive-cuffs`, {
    cuffs,
    ward_contact_name: wardContactName ?? null,
  });
  return resp.data;
}
