import { api } from "@/services/api";
import type { Checks, ChecklistKind, Cuffs, EquipmentSource } from "@/types";

// Roadmap PR32 (D9): read-only Monitor feed. Roadmap PR29: only `has_hn` (an indicator);
// the HN is revealed per transaction through revealHn(), never listed here.
export type MonitorKind = "dispatch" | "receipt";

export interface MonitorEvent {
  id: string;
  kind: MonitorKind;
  event_at: string;
  business_date: string;
  shift: "day" | "night";
  ward: { id: string | null; name: string | null };
  operator: { id: string | null; full_name: string | null };
  equipment: {
    id: string;
    bcm_code: string | null;
    name: string;
    category: string | null;
    // Roadmap PR33 (D14): source badge (DEMO / ยืม); absent = pool.
    equipment_source?: EquipmentSource;
  };
  receipt_outcome: "usable" | "defective" | null;
  close_reason: string | null;
  // D22: display-only keyer label (sheet-synced rows); preferred over operator name.
  keyer_label?: string | null;
  // Roadmap PR27/PR28: event-side contact name, checklist and outstanding cuffs.
  ward_contact_name?: string | null;
  checklist_kind?: ChecklistKind | null;
  checks?: Checks | null;
  cuffs_outstanding?: Cuffs | null;
  // Roadmap PR29 (D1): `id` (the transaction) has a patient HN recorded.
  has_hn?: boolean;
  // Roadmap PR34 (D15): an open dispatch (HN can still be added if has_hn is false).
  is_open?: boolean;
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
  cursor?: string;
  business_date_from?: string;
  business_date_to?: string;
}): Promise<MonitorPageResult> {
  const resp = await api.get<MonitorPageResult>("/monitor/events", { params });
  return resp.data;
}
