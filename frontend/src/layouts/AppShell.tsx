import { NavLink, Outlet, useNavigate } from "react-router-dom";

import {
  canDispatchOrReceiveEquipment,
  canManageEquipmentMasterData,
  canManageLegacyImport,
  canReviewCutoverReadiness,
  canReviewReconciliation,
  roleLabel,
  useAuth,
} from "@/hooks/useAuth";
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
];

export function AppShell() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const theme = useUiStore((s) => s.theme);
  const setTheme = useUiStore((s) => s.setTheme);
  const logoutStore = useAuthStore((s) => s.logout);

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
                `rounded-lg px-3 py-2 text-sm font-medium transition ${
                  isActive
                    ? "bg-status-borrowed/15 text-status-borrowed"
                    : "text-[var(--text-muted)] hover:bg-black/5 dark:hover:bg-white/5"
                }`
              }
            >
              <span className="mr-2">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
          {canManageEquipmentMasterData(user) && (
            <NavLink
              to="/admin"
              className={({ isActive }) =>
                `rounded-lg px-3 py-2 text-sm font-medium transition ${
                  isActive
                    ? "bg-status-borrowed/15 text-status-borrowed"
                    : "text-[var(--text-muted)] hover:bg-black/5 dark:hover:bg-white/5"
                }`
              }
            >
              <span className="mr-2">⚙️</span>
              จัดการระบบ
            </NavLink>
          )}
          {/* Roadmap PR19B: usability-only visibility gate, mirroring the
              /admin link above -- see hooks/useAuth.ts's
              canManageLegacyImport note. The real PR19A
              /import-sessions endpoints are Administrator-only
              (ADMINISTRATOR_ONLY_ROLES); this link is a usability mirror
              of that RBAC rule, not the enforcement boundary itself. */}
          {canManageLegacyImport(user) && (
            <NavLink
              to="/imports"
              className={({ isActive }) =>
                `rounded-lg px-3 py-2 text-sm font-medium transition ${
                  isActive
                    ? "bg-status-borrowed/15 text-status-borrowed"
                    : "text-[var(--text-muted)] hover:bg-black/5 dark:hover:bg-white/5"
                }`
              }
            >
              <span className="mr-2">📥</span>
              นำเข้าข้อมูลเดิม
            </NavLink>
          )}
          {/* Roadmap PR22F (§7/§37 of the task): a review/administrative
              workflow, not part of the primary daily dispatch flow, so it
              lives here in the desktop sidebar only -- deliberately NOT
              added to the mobile bottom nav below, to avoid crowding out
              ค้นหา/เบิก/รับคืน/รายงาน on a small screen. Visible to every
              authenticated role (mirrors backend VIEW_AND_REPORT_ROLES,
              see hooks/useAuth.ts's canReviewReconciliation), unlike
              /admin and /imports above which are Administrator-only.
              Mobile users reach this via the header link instead (see
              below) -- an existing "secondary surface" already visible
              at every breakpoint, per the task's own §7 guidance. */}
          {canReviewReconciliation(user) && (
            <NavLink
              to="/reconciliation"
              className={({ isActive }) =>
                `rounded-lg px-3 py-2 text-sm font-medium transition ${
                  isActive
                    ? "bg-status-borrowed/15 text-status-borrowed"
                    : "text-[var(--text-muted)] hover:bg-black/5 dark:hover:bg-white/5"
                }`
              }
            >
              <span className="mr-2">🔎</span>
              ตรวจสอบข้อมูลย้อนหลัง
            </NavLink>
          )}
          {/* Roadmap PR23E: another review/administrative workflow, same
              placement rationale as /reconciliation directly above --
              desktop sidebar only, reached on mobile via the header link
              below, visible to every authenticated role (mirrors backend
              VIEW_AND_REPORT_ROLES, see hooks/useAuth.ts's
              canReviewCutoverReadiness). */}
          {canReviewCutoverReadiness(user) && (
            <NavLink
              to="/cutover-readiness"
              className={({ isActive }) =>
                `rounded-lg px-3 py-2 text-sm font-medium transition ${
                  isActive
                    ? "bg-status-borrowed/15 text-status-borrowed"
                    : "text-[var(--text-muted)] hover:bg-black/5 dark:hover:bg-white/5"
                }`
              }
            >
              <span className="mr-2">🚦</span>
              ความพร้อมก่อนเปลี่ยนระบบ
            </NavLink>
          )}
        </nav>
      </aside>

      <div className="flex min-h-screen flex-1 flex-col">
        <header className="surface flex items-center justify-between border-b px-4 py-3">
          <div className="text-sm font-medium md:hidden">Medical Equipment Pool</div>
          <div className="hidden text-sm text-[var(--text-muted)] md:block">
            {user ? `${user.full_name} · ${roleLabel(user.role)}` : ""}
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={toggleTheme}
              className="rounded-lg px-2 py-1 text-lg hover:bg-black/5 dark:hover:bg-white/5"
              aria-label="สลับธีมสว่าง/มืด"
            >
              {theme === "dark" ? "☀️" : "🌙"}
            </button>
            {/* Roadmap PR22F: the header row renders at every breakpoint
                (unlike the sidebar, hidden below md), so this is the
                actual mobile access point for reconciliation review --
                deliberately not added to the mobile bottom nav (see the
                sidebar entry's own note above). */}
            {canReviewReconciliation(user) && (
              <NavLink to="/reconciliation" className="text-sm text-[var(--text-muted)] hover:underline md:hidden">
                ตรวจสอบข้อมูลย้อนหลัง
              </NavLink>
            )}
            {canReviewCutoverReadiness(user) && (
              <NavLink to="/cutover-readiness" className="text-sm text-[var(--text-muted)] hover:underline md:hidden">
                ความพร้อมก่อนเปลี่ยนระบบ
              </NavLink>
            )}
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
          {/* Roadmap PR19B: reuses the same mobile bottom-nav mechanism as
              every other item above (not a separate/invented nav pattern),
              gated by the same canManageLegacyImport capability check as
              the desktop sidebar's "นำเข้าข้อมูลเดิม" link -- see
              hooks/useAuth.ts's canManageLegacyImport note. Direct
              navigation to /imports remains guarded by
              LegacyImportAccessGate regardless of nav visibility. */}
          {canManageLegacyImport(user) && (
            <NavLink
              to="/imports"
              className={({ isActive }) =>
                `flex flex-1 flex-col items-center gap-0.5 py-2 text-xs ${
                  isActive ? "text-status-borrowed" : "text-[var(--text-muted)]"
                }`
              }
            >
              <span className="text-lg">📥</span>
              นำเข้าข้อมูลเดิม
            </NavLink>
          )}
        </nav>
      </div>
    </div>
  );
}
