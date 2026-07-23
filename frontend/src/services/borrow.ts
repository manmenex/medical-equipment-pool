import { api } from "@/services/api";
import type { DispatchType, Page, ReceiptOutcome, RoutineRound, TransactionOut, WardCorrectionPayload } from "@/types";

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

// Roadmap PR8B (backend/app/schemas/transaction.py's ReturnRequest,
// knowledge/adr/ADR-006-receipt-outcome-contract.md): condition is
// retired entirely -- receipt_outcome replaces it, no compatibility
// alias. The backend rejects an unrecognized field (extra: "forbid"), so
// this payload shape must match the current contract exactly.
export interface ReturnPayload {
  receipt_outcome: ReceiptOutcome;
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

export async function getTransaction(transactionId: string): Promise<TransactionOut> {
  const resp = await api.get<TransactionOut>(`/transactions/${transactionId}`);
  return resp.data;
}

// Roadmap PR9A (backend/app/schemas/transaction.py): the mandatory reason's
// declared maximum length, mirrored here so the frontend's own validation
// and character counter can never silently drift from the backend's
// authoritative limit.
export const WARD_CORRECTION_REASON_MAX_LENGTH = 500;

// Roadmap PR9B: consumes the merged PR9A backend contract exactly --
// POST /transactions/{id}/correct-ward, body { ward_id, reason }, response
// is the existing TransactionOut with the corrected ward_id. This backend
// contract is not changed by PR9B; see docs/api/transactions.md.
export async function correctTransactionWard(
  transactionId: string,
  payload: WardCorrectionPayload
): Promise<TransactionOut> {
  const resp = await api.post<TransactionOut>(`/transactions/${transactionId}/correct-ward`, payload);
  return resp.data;
}
