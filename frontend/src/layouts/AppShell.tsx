import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { UpdateNotice } from "@/components/UpdateNotice";
import { OfflineStatusChip } from "@/components/OfflineStatusChip";
import {
  canDispatchOrReceiveEquipment,
  canReviewSyncConflicts,
  roleLabel,
  useAuth,
} from "@/hooks/useAuth";
import { startOfflineServices } from "@/offline/lifecycle";
import { fetchSyncConflicts } from "@/services/syncReview";
import { logout as apiLogout } from "@/services/auth";
import { useAuthStore } from "@/store/authStore";
import { applyTheme, useUiStore } from "@/store/uiStore";

const BASE_NAV_ITEMS = [
  { to: "/", label: "หน้าหลัก", icon: "🏠" },
  { to: "/equipment", label: "ค้นหา", icon: "🔍" },
  { to: "/reports", label: "รายงาน", icon: "📊" },
];

// Roadmap PR10: dispatch/receipt (เบิก/รับคืน) nav entries are hidden for a
// user who cannot perform them (Read Only) -- usability only, not a
// security boundary; see hooks/useAuth.ts's capability-layer note.
// Roadmap PR11: labels use "เบิก"/"รับคืน" (issue/receive) consistently --
// never "ยืม"/"คืน" (borrow/return), which the confirmed workflow
// terminology retires everywhere in the UI (docs/audits/
// 04-consolidated-implementation-plan.md Part D, PR11 acceptance criteria).
const DISPATCH_NAV_ITEMS = [
  { to: "/borrow", label: "เบิก", icon: "📷" },
  { to: "/return", label: "รับคืน", icon: "↩️" },
  // Roadmap PR32 (D9/D13): read-only Monitor, Equipment Pool staff + admin.
  { to: "/monitor", label: "Monitor การจ่าย/รับ", icon: "🖥️" },
  // Roadmap PR34 (D16): standby summary, Equipment Pool staff + admin.
  { to: "/standby-summary", label: "สรุป Stand By", icon: "📋" },
];

export function AppShell() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const theme = useUiStore((s) => s.theme);
  const setTheme = useUiStore((s) => s.setTheme);
  const logoutStore = useAuthStore((s) => s.logout);

  // PR25E S4: sync worker + snapshot refresh run for the whole signed-in shell.
  useEffect(() => startOfflineServices(), []);

  // PR25E S5: pending-review count badge, role-gated (no request for Read Only).
  const reviewAllowed = canReviewSyncConflicts(user);
  const reviewCount = useQuery({
    queryKey: ["sync-conflicts-count"],
    queryFn: () => fetchSyncConflicts({ limit: 1 }),
    enabled: reviewAllowed,
    refetchInterval: 60_000,
    retry: false,
  }).data?.total;

  const navItems = canDispatchOrReceiveEquipment(user)
    ? [BASE_NAV_ITEMS[0], BASE_NAV_ITEMS[1], ...DISPATCH_NAV_ITEMS, BASE_NAV_ITEMS[2]]
    : BASE_NAV_ITEMS;

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    applyTheme(next);
  };

  const handleLogout = async () => {
    try {
      await apiLogout();
    } finally {
      logoutStore();
      navigate("/login", { replace: true });
    }
  };

  return (
    <div className="flex min-h-screen">
      <aside className="surface hidden w-56 flex-col border-r p-4 md:flex">
        <div className="mb-6 text-lg font-semibold">Medical Equipment Pool</div>
        <nav className="flex flex-1 flex-col gap-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `flex min-h-[44px] items-center rounded-lg px-3 py-2 text-sm font-medium transition ${
                  isActive
                    ? "bg-status-borrowed font-semibold text-white"
                    : "text-[var(--text)] hover:bg-black/10 dark:hover:bg-white/10"
                }`
              }
            >
              <span className="mr-2">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
          {/* Data-management and migration entries live in the Settings hub
              (pages/SettingsPage.tsx); the sidebar keeps daily work plus a
              Settings entry that carries the offline-review count badge. */}
          <NavLink
            to="/settings"
            className={({ isActive }) =>
              `flex min-h-[44px] items-center rounded-lg px-3 py-2 text-sm font-medium transition ${
                isActive
                  ? "bg-status-borrowed font-semibold text-white"
                  : "text-[var(--text)] hover:bg-black/10 dark:hover:bg-white/10"
              }`
            }
          >
            <span className="mr-2">⚙️</span>
            ตั้งค่า
            {reviewAllowed && reviewCount ? (
              <span
                aria-label={`รอตรวจสอบ ${reviewCount} รายการ`}
                className="ml-2 rounded-full bg-status-repair px-2 py-0.5 text-xs text-white"
              >
                {reviewCount}
              </span>
            ) : null}
          </NavLink>
        </nav>
      </aside>

      <div className="flex min-h-screen min-w-0 flex-1 flex-col">
        <UpdateNotice />
        <header className="surface flex items-center justify-between border-b px-4 py-3">
          <div className="text-sm font-medium md:hidden">Medical Equipment Pool</div>
          <div className="hidden text-sm text-[var(--text-muted)] md:block">
            {user ? `${user.full_name} · ${roleLabel(user.role)}` : ""}
          </div>
          <div className="flex items-center gap-3">
            <OfflineStatusChip />
            <button
              onClick={toggleTheme}
              className="rounded-lg px-2 py-1 text-lg hover:bg-black/5 dark:hover:bg-white/5"
              aria-label="สลับธีมสว่าง/มืด"
            >
              {theme === "dark" ? "☀️" : "🌙"}
            </button>
            <NavLink to="/settings" className="text-sm text-[var(--text-muted)] hover:underline">
              ตั้งค่า
            </NavLink>
            <button onClick={handleLogout} className="text-sm text-status-repair hover:underline">
              ออกจากระบบ
            </button>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto p-4 pb-20 md:pb-4">
          <Outlet />
        </main>

        <nav className="surface fixed inset-x-0 bottom-0 flex border-t md:hidden">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `flex flex-1 flex-col items-center gap-0.5 py-2 text-xs ${
                  isActive ? "text-status-borrowed" : "text-[var(--text-muted)]"
                }`
              }
            >
              <span className="text-lg">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
      </div>
    </div>
  );
}
