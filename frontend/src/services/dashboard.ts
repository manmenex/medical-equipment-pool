import { api } from "@/services/api";
import type { BorrowTrendPoint, DashboardSummary, TopBorrowedItem } from "@/types";

// Roadmap PR33 (D14): source filter (all/pool/demo/loan), default all.
export type DashboardSource = "all" | "pool" | "demo" | "loan";

export async function fetchSummary(source: DashboardSource = "all"): Promise<DashboardSummary> {
  const resp = await api.get<DashboardSummary>("/dashboard/summary", {
    params: source === "all" ? undefined : { source },
  });
  return resp.data;
}

export async function fetchBorrowTrend(range = 30): Promise<BorrowTrendPoint[]> {
  const resp = await api.get<BorrowTrendPoint[]>("/dashboard/borrow-trend", { params: { range } });
  return resp.data;
}

export async function fetchTopBorrowed(limit = 10): Promise<TopBorrowedItem[]> {
  const resp = await api.get<TopBorrowedItem[]>("/dashboard/top-borrowed", { params: { limit } });
  return resp.data;
}
