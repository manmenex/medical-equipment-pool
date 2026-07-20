import { api } from "@/services/api";
import type { DispatchType, Page, RoutineRound, TransactionOut } from "@/types";

// Roadmap PR7b: borrower_name/due_at/quantity are deliberately absent --
// no longer accepted by the active BorrowRequest contract (see
// backend/app/schemas/transaction.py). ward_id and dispatch_type are now
// required; routine_round is required only for a routine_round dispatch.
export interface BorrowPayload {
  equipment_id: string;
  ward_id: string;
  dispatch_type: DispatchType;
  routine_round?: RoutineRound;
  department_id?: string;
  phone_number?: string;
  pickup_location_id?: string;
  dropoff_location_id?: string;
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
