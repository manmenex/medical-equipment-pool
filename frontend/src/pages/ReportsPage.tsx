import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/services/api";
import { fetchBorrowTrend } from "@/services/dashboard";
import { BarChart, Bar, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export function ReportsPage() {
  const [range, setRange] = useState(30);
  const { data: trend } = useQuery({
    queryKey: ["reports", "trend", range],
    queryFn: () => fetchBorrowTrend(range),
  });

  const download = async (format: "xlsx" | "csv") => {
    const resp = await api.get("/reports/export", { params: { format }, responseType: "blob" });
    const url = URL.createObjectURL(resp.data as Blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `borrow_report.${format}`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">รายงาน</h1>
        <select
          value={range}
          onChange={(e) => setRange(Number(e.target.value))}
          className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm"
        >
          <option value={7}>7 วันล่าสุด</option>
          <option value={30}>30 วันล่าสุด</option>
          <option value={90}>90 วันล่าสุด</option>
        </select>
        <div className="ml-auto flex gap-2">
          <button
            onClick={() => download("xlsx")}
            className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
          >
            Export Excel
          </button>
          <button
            onClick={() => download("csv")}
            className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
          >
            Export CSV
          </button>
        </div>
      </div>

      <div className="surface rounded-xl border p-4">
        <div className="mb-3 text-sm font-medium">Borrow Frequency</div>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={trend ?? []}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} />
            <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
            <Tooltip />
            <Bar dataKey="count" fill="#2563EB" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
