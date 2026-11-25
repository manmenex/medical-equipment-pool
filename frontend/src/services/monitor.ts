import { api } from "@/services/api";

// Roadmap PR32 (D9): read-only Monitor feed. No HN field exists in this contract.
export type MonitorKind = "dispatch" | "receipt";

export interface MonitorEvent {
  id: string;
  kind: MonitorKind;
  event_at: string;
  business_date: string;
  shift: "day" | "night";
  ward: { id: string | null; name: string | null };
  operator: { id: string | null; full_name: string | null };
  equipment: { id: string; bcm_code: string | null; name: string; category: string | null };
  receipt_outcome: "usable" | "defective" | null;
  close_reason: string | null;
}

export interface MonitorPageResult {
  items: MonitorEvent[];
  next_cursor: string | null;
  total: number;
}

export async function fetchMonitorEvents(params: {
  kind: MonitorKind;
  ward_id?: string;
  q?: string;
  limit?: number;
}): Promise<MonitorPageResult> {
  const resp = await api.get<MonitorPageResult>("/monitor/events", { params });
  return resp.data;
}
