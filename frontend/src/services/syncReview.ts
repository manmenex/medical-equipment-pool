import { api } from "@/services/api";

// PR25E S5: thin wrappers over the B4 conflict review API (docs/api/sync.md,
// "Conflict review (slice B4)"). All eligibility decisions stay server-side.

export type DismissReason = "already_recorded" | "duplicate_physical_entry" | "not_real" | "handled_elsewhere";

export interface SyncPerson {
  id: string;
  full_name: string;
}

export interface SyncConflictItem {
  op_id: string;
  op_type: string;
  status: string;
  result_code: string | null;
  admin_only: boolean;
  stale_context: boolean;
  time_flag?: string | null;
  device_id: string | null;
  received_at: string | null;
  first_seen_at: string | null;
  occurred_at: string | null;
  attempt_count: number;
  operator: SyncPerson | null;
  submitted_by?: SyncPerson | null;
  equipment: { id: string; bcm_code: string | null; equipment_name: string | null; status: string | null } | null;
  ward_name: string | null;
  transaction_id: string | null;
  receipt_outcome: string | null;
  resolution: string | null;
  dismiss_reason: string | null;
}

export interface SyncConflictPage {
  total: number;
  limit: number;
  offset: number;
  items: SyncConflictItem[];
}

export async function fetchSyncConflicts(params: { limit?: number; offset?: number } = {}): Promise<SyncConflictPage> {
  const resp = await api.get<SyncConflictPage>("/sync/conflicts", { params });
  return resp.data;
}

export async function dismissSyncConflict(opId: string, reason: DismissReason, note?: string): Promise<void> {
  await api.post(`/sync/conflicts/${opId}/dismiss`, note ? { reason, note } : { reason });
}

export async function applySyncConflictNow(opId: string): Promise<void> {
  await api.post(`/sync/conflicts/${opId}/apply-now`);
}
