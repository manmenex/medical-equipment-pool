import { api } from "@/services/api";

// PR25E S3: thin client for the sync endpoints (docs/api/sync.md). Kept apart
// from the worker so wiring POST /sync/verify (B3) later is a one-function add.

export type SyncResultStatus = "applied" | "duplicate" | "conflict" | "rejected" | "retry_later";

export interface SyncOperationResult {
  op_id: string;
  result: SyncResultStatus;
  code: string;
  transaction_id?: string | null;
  message?: string;
}

export const MAX_BATCH_OPS = 25;

export async function postOperations(envelopes: Record<string, unknown>[]): Promise<SyncOperationResult[]> {
  const resp = await api.post<{ results: SyncOperationResult[] }>("/sync/operations", {
    operations: envelopes,
  });
  return resp.data.results;
}
