import { api } from "@/services/api";

// PR25E B4b: per-equipment timeline, human-confirmed Apply sequence and
// collision statistics (docs/api/sync.md, "Timeline, Apply sequence and
// collision statistics"). All eligibility decisions stay server-side.

export interface TimelineEvent {
  source: "transaction" | "op";
  kind: "dispatch" | "receipt";
  at: string;
  band_s: number;
  order_uncertain: boolean;
  selectable: boolean;
  op_id?: string | null;
  status?: string | null;
  result_code?: string | null;
  admin_only?: boolean;
  stale_context?: boolean;
  time_flag?: string | null;
  device_id?: string | null;
  device_seq?: number | null;
  operator?: { id: string; full_name: string } | null;
  ward_name?: string | null;
  receipt_outcome?: string | null;
  transaction_id?: string | null;
}

export interface EquipmentTimeline {
  equipment: { id: string; bcm_code: string | null; equipment_name: string; status: string };
  server_time: string;
  events: TimelineEvent[];
}

export interface SequenceStep {
  op_id: string;
  ok: boolean;
  code?: string | null;
  message?: string | null;
  new_op_id?: string | null;
  transaction_id?: string | null;
}

export interface ApplySequenceResult {
  dry_run: boolean;
  steps: SequenceStep[];
  failed: SequenceStep | null;
  remaining: string[];
}

export interface CollisionStats {
  range_from: string;
  range_to: string;
  total_conflicts: number;
  by_result_code: Record<string, number>;
  by_status: Record<string, number>;
  by_day: Record<string, number>;
  truncated: boolean;
  groups: {
    equipment_with_multiple_conflicts: number;
    cross_device: number;
    by_outcome: Record<string, number>;
    agreement_rate: number | null;
    would_have_auto_sequenced: {
      conditions_met: number;
      resolved_same_order: number;
      resolved_differently: number;
      agreement_rate: number | null;
    };
  };
}

export async function fetchEquipmentTimeline(equipmentId: string): Promise<EquipmentTimeline> {
  const resp = await api.get<EquipmentTimeline>(`/sync/equipment/${equipmentId}/timeline`);
  return resp.data;
}

export async function applySequence(
  equipmentId: string,
  opIds: string[],
  dryRun = false,
): Promise<ApplySequenceResult> {
  const resp = await api.post<ApplySequenceResult>(`/sync/equipment/${equipmentId}/apply-sequence`, {
    op_ids: opIds,
    dry_run: dryRun,
  });
  return resp.data;
}

export async function fetchCollisionStats(): Promise<CollisionStats> {
  const resp = await api.get<CollisionStats>("/sync/collisions/stats");
  return resp.data;
}

export async function downloadCollisionCsv(): Promise<void> {
  const resp = await api.get("/sync/collisions/export", { responseType: "blob" });
  const url = URL.createObjectURL(resp.data as Blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "sync-conflicts.csv";
  a.click();
  URL.revokeObjectURL(url);
}
