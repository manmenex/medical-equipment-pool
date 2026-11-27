import { api } from "@/services/api";
import type {
  Checks,
  CorrectionOut,
  Cuffs,
  DispatchType,
  EquipmentStatus,
  Page,
  ReceiptOutcome,
  RoutineRound,
  Shift,
  TransactionEventBasis,
  TransactionOut,
  WardCorrectionPayload,
} from "@/types";

// Roadmap PR7b: borrower_name/due_at/quantity are deliberately absent --
// no longer accepted by the active BorrowRequest contract (see
// backend/app/schemas/transaction.py). ward_id and dispatch_type are now
// required; routine_round is required only for a routine_round dispatch.
export interface BorrowPayload {
  equipment_id: string;
  ward_id: string;
  // Roadmap PR26: no longer collected by the dispatch form; kept optional
  // for backward compatibility with queued offline operations.
  dispatch_type?: DispatchType;
  routine_round?: RoutineRound;
  department_id?: string;
  phone_number?: string;
  pickup_location_id?: string;
  dropoff_location_id?: string;
  notes?: string;
  // Roadmap PR31 (D8): sent only after the operator confirmed a
  // DISPATCH_STATUS_WARNING (already dispatched / defective).
  acknowledge_status_warning?: boolean;
  // Roadmap PR31 review: the open transaction the warning was about; the
  // backend refuses a stale acknowledgement (DISPATCH_WARNING_STALE).
  expected_open_transaction_id?: string;
  // Roadmap PR27/PR28: ward contact name, accessory checklist, stale-status guard.
  ward_contact_name?: string;
  dispatch_checks?: Checks;
  expected_status?: EquipmentStatus;
  // Roadmap PR29 (D1): optional patient HN (write-only; never returned).
  hn?: string;
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
  ward_contact_name?: string;
  receipt_checks?: Checks;
  cuffs_returned?: Partial<Cuffs>;
}

// Roadmap PR27/PR28 (docs/api/ward-first-entry.md section 5): ward-first batch.
export interface BatchItemError {
  code: string;
  message: string;
  status: number;
  details?: Record<string, unknown> | null;
}

export interface BatchItemResult {
  index: number;
  ok: boolean;
  equipment_id: string | null;
  transaction_id: string | null;
  transaction_no: string | null;
  cuffs_outstanding: Cuffs | null;
  error: BatchItemError | null;
}

export interface BatchResponse {
  total: number;
  succeeded: number;
  failed: number;
  results: BatchItemResult[];
}

export interface DispatchBatchItem {
  equipment_id: string;
  checks: Checks | null;
  acknowledge_status_warning?: boolean;
  expected_open_transaction_id?: string | null;
  expected_status?: EquipmentStatus | null;
  // Roadmap PR29 (D1): optional patient HN of this equipment (write-only).
  hn?: string;
}

export interface DispatchBatchPayload {
  ward_id: string;
  ward_contact_name?: string | null;
  phone?: string | null;
  note?: string | null;
  items: DispatchBatchItem[];
}

export interface ReceiptBatchItem {
  transaction_id?: string;
  equipment_id?: string;
  receipt_outcome: ReceiptOutcome;
  checks: Checks | null;
  cuffs_returned?: Partial<Cuffs> | null;
}

export interface ReceiptBatchPayload {
  ward_id?: string | null;
  ward_contact_name?: string | null;
  note?: string | null;
  items: ReceiptBatchItem[];
}

export async function dispatchBatch(payload: DispatchBatchPayload): Promise<BatchResponse> {
  return (await api.post<BatchResponse>("/transactions/dispatch-batch", payload)).data;
}

export async function receiptBatch(payload: ReceiptBatchPayload): Promise<BatchResponse> {
  return (await api.post<BatchResponse>("/transactions/receipt-batch", payload)).data;
}

/**
 * Roadmap PR29 (D1/D13): the ONLY call that returns a patient HN. Staff and
 * administrators; the server writes an audit row (who/when/which transaction,
 * never the value). Callers must keep the value in component state only and
 * hide it again after REVEAL_SECONDS.
 */
export async function revealHn(transactionId: string): Promise<string> {
  const resp = await api.post<{ hn: string }>(`/transactions/${transactionId}/reveal-hn`);
  return resp.data.hn;
}

/**
 * Roadmap PR34 (D15): add an HN to an OPEN dispatch that has none (Standby ->
 * in use). Online only. The response carries `has_hn` only, never the value.
 */
export async function addHn(transactionId: string, hn: string): Promise<TransactionOut> {
  const resp = await api.post<TransactionOut>(`/transactions/${transactionId}/hn`, { hn });
  return resp.data;
}

export async function createReturn(transactionId: string, payload: ReturnPayload): Promise<TransactionOut> {
  const resp = await api.post<TransactionOut>(`/return/${transactionId}`, payload);
  return resp.data;
}

export async function listTransactions(params: {
  ward_id?: string;
  equipment_id?: string;
  status?: string;
  // Roadmap PR13: dispatch-type/round-aware history filtering, plus a
  // date range bounding the dispatch (borrowed_at) date -- all optional
  // and independently combinable, mirroring backend/app/crud/transaction.py's
  // search().
  dispatch_type?: DispatchType;
  routine_round?: RoutineRound;
  from_date?: string;
  to_date?: string;
  // Roadmap PR16 Slice 3 (backend/app/crud/transaction.py's search()):
  // a distinct filter basis from from_date/to_date above -- these compare
  // against the backend-derived business_date/shift, never the raw
  // borrowed_at/returned_at timestamp. Parameter names match the backend
  // query contract exactly; no alias or rename.
  business_date_from?: string;
  business_date_to?: string;
  shift?: Shift;
  event?: TransactionEventBasis;
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

// Owner Governance 2026-11-27 (D28): audited undo / void / change-device /
// switch-action (docs/api/transactions.md). The server is the authority for
// permission, window and state guards; callers surface its message.
export async function undoTransaction(transactionId: string): Promise<CorrectionOut> {
  return (await api.post<CorrectionOut>(`/transactions/${transactionId}/undo`)).data;
}

export async function voidTransaction(transactionId: string, reason: string): Promise<CorrectionOut> {
  return (await api.post<CorrectionOut>(`/transactions/${transactionId}/void`, { reason })).data;
}

export async function changeTransactionDevice(
  transactionId: string,
  payload: { reason: string; equipment_id: string; acknowledge_status_warning?: boolean }
): Promise<CorrectionOut> {
  return (await api.post<CorrectionOut>(`/transactions/${transactionId}/change-device`, payload)).data;
}

export async function switchTransactionAction(
  transactionId: string,
  payload: { reason: string; outcome?: ReceiptOutcome; ward_id?: string }
): Promise<CorrectionOut> {
  return (await api.post<CorrectionOut>(`/transactions/${transactionId}/switch-action`, payload)).data;
}
