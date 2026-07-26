import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { StatCard } from "@/components/StatCard";
import { canDispatchOrReceiveEquipment, useAuth } from "@/hooks/useAuth";
import { fetchSummary } from "@/services/dashboard";

// Roadmap PR12 (Dashboard & Equipment Status): the dashboard's job is to
// let staff understand current Equipment Pool status and reach frequent
// workflows quickly -- simple operational counts and quick actions only.
// No trend/frequency charts here (that analysis lives on ReportsPage.tsx,
// out of scope for this PR); PM/Calibration due-soon and the running total
// are kept because they are the same kind of simple count, not a chart.
interface QuickAction {
  to: string;
  icon: string;
  label: string;
}

const QUICK_ACTIONS: QuickAction[] = [
  { to: "/scan", icon: "📷", label: "สแกน QR" },
  { to: "/equipment", icon: "📋", label: "ดูรายการเครื่อง" },
  { to: "/reports", icon: "🕘", label: "ดูประวัติรายการ" },
];

// Dispatch/receipt quick actions are permission-gated the same way
// AppShell.tsx gates its own dispatch/receipt nav entries (canDispatchOrReceiveEquipment) --
// usability only, never a security boundary; the backend remains authoritative.
const DISPATCH_QUICK_ACTIONS: QuickAction[] = [
  { to: "/borrow", icon: "📤", label: "จ่ายเครื่อง" },
  { to: "/return", icon: "📥", label: "รับเครื่อง" },
];

function QuickActionLink({ to, icon, label }: QuickAction) {
  return (
    <Link
      to={to}
      className="surface flex min-h-[88px] flex-col items-center justify-center gap-1 rounded-xl border p-4 text-center transition hover:shadow-md"
    >
      <span className="text-2xl" aria-hidden="true">
        {icon}
      </span>
      <span className="text-sm font-medium">{label}</span>
    </Link>
  );
}

export function DashboardPage() {
  const { user } = useAuth();
  const canDispatchOrReceive = canDispatchOrReceiveEquipment(user);

  const {
    data: summary,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["dashboard", "summary"],
    queryFn: fetchSummary,
    refetchInterval: 15000,
  });

  const isEmpty = !isLoading && !isError && (summary?.total ?? 0) === 0;

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-lg font-semibold">ภาพรวมระบบ</h1>

      {isLoading && <p className="text-sm text-[var(--text-muted)]">กำลังโหลด...</p>}

      {isError && (
        <div className="flex flex-col items-start gap-2">
          <p className="text-sm text-status-repair">ไม่สามารถโหลดข้อมูลภาพรวมได้</p>
          <button
            type="button"
            onClick={() => refetch()}
            className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
          >
            ลองใหม่
          </button>
        </div>
      )}

      {isEmpty && <p className="text-sm text-[var(--text-muted)]">ยังไม่มีข้อมูลเครื่องมือในระบบ</p>}

      {!isLoading && !isError && !isEmpty && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-8">
            <StatCard label="ทั้งหมด" value={summary?.total ?? 0} to="/equipment" />
            <StatCard
              label="พร้อมใช้งาน"
              value={summary?.available_at_pool ?? 0}
              to="/equipment?status=available_at_pool"
              accentClassName="text-status-available"
            />
            <StatCard
              label="จ่ายให้หอผู้ป่วยแล้ว"
              value={summary?.issued_to_ward ?? 0}
              to="/equipment?status=issued_to_ward"
              accentClassName="text-status-borrowed"
            />
            <StatCard
              label="ไม่พร้อมใช้งาน"
              value={summary?.unavailable_defective ?? 0}
              to="/equipment?status=unavailable_defective"
              accentClassName="text-status-repair"
            />
            <StatCard
              label="ปลดระวางถาวร"
              value={summary?.decommissioned ?? 0}
              to="/equipment?status=decommissioned"
              accentClassName="text-status-out_of_service"
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
        </>
      )}

      <div>
        <div className="mb-2 text-sm font-medium text-[var(--text-muted)]">การดำเนินการด่วน</div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {canDispatchOrReceive && <QuickActionLink {...DISPATCH_QUICK_ACTIONS[0]} />}
          {canDispatchOrReceive && <QuickActionLink {...DISPATCH_QUICK_ACTIONS[1]} />}
          {QUICK_ACTIONS.map((action) => (
            <QuickActionLink key={action.to} {...action} />
          ))}
        </div>
      </div>
    </div>
  );
}
