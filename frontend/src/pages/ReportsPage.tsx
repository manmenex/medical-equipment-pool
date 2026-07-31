import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

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
    a.download = `dispatch_report.${format}`;
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
            ส่งออก Excel
          </button>
          <button
            onClick={() => download("csv")}
            className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
          >
            ส่งออก CSV
          </button>
        </div>
      </div>

      {/* Roadmap PR17 Slice 3 (docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md
          §12): entry points to the two new named report screens -- reuses
          this existing /reports page as the navigation hub rather than
          adding new top-level sidebar entries. The trend chart/export
          above are unchanged. */}
      <div className="flex flex-wrap gap-2">
        <Link
          to="/reports/receive"
          className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium"
        >
          รายงานการรับคืน
        </Link>
        <Link
          to="/reports/issue"
          className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium"
        >
          รายงานการเบิก
        </Link>
        {/* Roadmap PR17 Slice 4: final PR17 report entry point. */}
        <Link
          to="/reports/equipment-verify-checklist"
          className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium"
        >
          รายการตรวจสอบเครื่องมือ
        </Link>
      </div>

      <div className="surface rounded-xl border p-4">
        <div className="mb-3 text-sm font-medium">ความถี่การเบิก</div>
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
