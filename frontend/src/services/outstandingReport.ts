import { api } from "@/services/api";

// Owner Governance 2026-11-28 (D30): read-only long-outstanding dispatch
// report. has_hn is a boolean only; the HN value never reaches the client.
export interface OutstandingRow {
  transaction_no: string;
  bcm_code: string | null;
  equipment_name: string;
  category: string | null;
  source: string;
  source_badge: string | null;
  ward: string;
  borrowed_at: string;
  age_days: number;
  keyer: string | null;
  has_hn: boolean;
}

export interface OutstandingWard {
  ward: string;
  count: number;
  rows: OutstandingRow[];
}

export interface OutstandingReport {
  days: number;
  total: number;
  wards: OutstandingWard[];
}

export async function fetchOutstanding(days: number): Promise<OutstandingReport> {
  return (await api.get<OutstandingReport>("/reports/outstanding", { params: { days } })).data;
}

export async function fetchOutstandingLineText(days: number): Promise<string> {
  return (await api.get<string>("/reports/outstanding/line-text", { params: { days }, responseType: "text" })).data;
}
