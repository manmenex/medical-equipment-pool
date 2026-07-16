import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { StatCard } from "@/components/StatCard";
import { fetchBorrowTrend, fetchSummary, fetchTopBorrowed } from "@/services/dashboard";

export function DashboardPage() {
  const { data: summary } = useQuery({
    queryKey: ["dashboard", "summary"],
    queryFn: fetchSummary,
    refetchInterval: 15000,
  });
  const { data: trend } = useQuery({
    queryKey: ["dashboard", "trend"],
    queryFn: () => fetchBorrowTrend(30),
    refetchInterval: 60000,
  });
  const { data: topBorrowed } = useQuery({
    queryKey: ["dashboard", "top"],
    queryFn: () => fetchTopBorrowed(10),
    refetchInterval: 60000,
  });

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-8">
        <StatCard label="ทั้งหมด" value={summary?.total ?? 0} to="/equipment" />
        <StatCard
          label="พร้อมใช้งาน"
          value={summary?.available ?? 0}
          to="/equipment?status=available"
          accentClassName="text-status-available"
        />
        <StatCard
          label="ถูกยืม"
          value={summary?.borrowed ?? 0}
          to="/equipment?status=borrowed"
          accentClassName="text-status-borrowed"
        />
        <StatCard
          label="ทำความสะอาด"
          value={summary?.cleaning ?? 0}
          to="/equipment?status=cleaning"
          accentClassName="text-status-cleaning"
        />
        <StatCard label="PM" value={summary?.pm ?? 0} to="/equipment?status=pm" accentClassName="text-status-pm" />
        <StatCard
          label="สอบเทียบ"
          value={summary?.calibration ?? 0}
          to="/equipment?status=calibration"
          accentClassName="text-status-calibration"
        />
        <StatCard
          label="ซ่อม"
          value={summary?.repair ?? 0}
          to="/equipment?status=repair"
          accentClassName="text-status-repair"
        />
        <StatCard
          label="สูญหาย"
          value={summary?.lost ?? 0}
          to="/equipment?status=lost"
          accentClassName="text-status-lost"
        />
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div className="surface rounded-xl border p-4">
          <div className="mb-1 text-sm font-medium">PM ใกล้ครบกำหนด (7 วัน)</div>
          <div className="text-2xl font-semibold text-status-pm">{summary?.pm_due_soon ?? 0} เครื่อง</div>
        </div>
        <div className="surface rounded-xl border p-4">
          <div className="mb-1 text-sm font-medium">Calibration ใกล้ครบกำหนด (7 วัน)</div>
          <div className="text-2xl font-semibold text-status-calibration">{summary?.cal_due_soon ?? 0} เครื่อง</div>
        </div>
      </div>

      <div className="surface rounded-xl border p-4">
        <div className="mb-3 text-sm font-medium">แนวโน้มการยืม (30 วัน)</div>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={trend ?? []}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} />
            <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
            <Tooltip />
            <Line type="monotone" dataKey="count" stroke="#2563EB" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="surface rounded-xl border p-4">
        <div className="mb-3 text-sm font-medium">เครื่องที่ถูกยืมบ่อยที่สุด</div>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={topBorrowed ?? []} layout="vertical" margin={{ left: 24 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} />
            <YAxis type="category" dataKey="asset_number" tick={{ fontSize: 11 }} width={90} />
            <Tooltip />
            <Bar dataKey="borrow_count" fill="#2563EB" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
