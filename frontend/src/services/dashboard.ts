import { api } from "@/services/api";
import type { BorrowTrendPoint, DashboardSummary, TopBorrowedItem } from "@/types";

export async function fetchSummary(): Promise<DashboardSummary> {
  const resp = await api.get<DashboardSummary>("/dashboard/summary");
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
