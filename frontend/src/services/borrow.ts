import { api } from "@/services/api";
import type { Page, TransactionOut } from "@/types";

export interface BorrowPayload {
  equipment_qr?: string;
  equipment_id?: string;
  borrower_name: string;
  ward_id?: string;
  department_id?: string;
  phone_number?: string;
  pickup_location_id?: string;
  dropoff_location_id?: string;
  quantity?: number;
  notes?: string;
}

export async function createBorrow(payload: BorrowPayload): Promise<TransactionOut> {
  const resp = await api.post<TransactionOut>("/borrow", payload);
  return resp.data;
}

export async function listActiveBorrows(): Promise<TransactionOut[]> {
  const resp = await api.get<TransactionOut[]>("/borrow/active");
  return resp.data;
}

export interface ReturnPayload {
  condition: string;
  notes?: string;
}

export async function createReturn(transactionId: string, payload: ReturnPayload): Promise<TransactionOut> {
  const resp = await api.post<TransactionOut>(`/return/${transactionId}`, payload);
  return resp.data;
}

export async function listTransactions(params: {
  ward_id?: string;
  equipment_id?: string;
  status?: string;
  cursor?: string | null;
  limit?: number;
}): Promise<Page<TransactionOut>> {
  const resp = await api.get<Page<TransactionOut>>("/transactions", { params });
  return resp.data;
}
