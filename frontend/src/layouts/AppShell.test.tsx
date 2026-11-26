import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { AppShell } from "@/layouts/AppShell";
import type { UserProfile } from "@/types";

// Roadmap PR19B "Routing and authorization" coverage: the "นำเข้าข้อมูลเดิม"
// nav entry is a usability-only gate (hooks/useAuth.ts's
// canManageLegacyImport) -- shown for administrator, hidden otherwise.
let mockUser: UserProfile | null = null;
vi.mock("@/hooks/useAuth", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useAuth")>("@/hooks/useAuth");
  return {
    ...actual,
    useAuth: () => ({ user: mockUser, isAuthenticated: true, isLoading: false }),
  };
});

function makeUser(role: UserProfile["role"]): UserProfile {
  return { id: "user-1", employee_code: "U001", full_name: "Test User", email: "u@test.dev", role, permissions: {}, must_change_password: false };
}

function renderShell() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<div>home</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

// Data-management and migration entries moved into the Settings hub
// (pages/SettingsPage.tsx); the shell keeps daily work plus ตั้งค่า.
const MOVED_LINKS = [
  /นำเข้าข้อมูลเดิม/,
  /ตรวจสอบข้อมูลย้อนหลัง/,
  /ความพร้อมก่อนเปลี่ยนระบบ/,
  /ตรวจสอบรายการออฟไลน์/,
  /^⚙️\s*จัดการระบบ$/,
];

describe("AppShell navigation", () => {
  it.each(["administrator", "equipment_pool_staff", "read_only"] as const)(
    "does not list data-management links in sidebar, header or bottom nav for %s",
    (role) => {
      mockUser = makeUser(role);
      renderShell();
      for (const name of MOVED_LINKS) {
        expect(screen.queryByRole("link", { name })).not.toBeInTheDocument();
      }
      expect(screen.queryByRole("link", { name: "จัดการระบบ" })).not.toBeInTheDocument();
    }
  );

  it.each(["administrator", "equipment_pool_staff", "read_only"] as const)(
    "shows ตั้งค่า in the sidebar and header for %s",
    (role) => {
      mockUser = makeUser(role);
      renderShell();
      const links = screen.getAllByRole("link", { name: /ตั้งค่า/ });
      expect(links).toHaveLength(2);
      for (const link of links) expect(link).toHaveAttribute("href", "/settings");
    }
  );

  it("keeps the daily-work links for pool staff", () => {
    mockUser = makeUser("equipment_pool_staff");
    renderShell();
    for (const name of [/หน้าหลัก/, /ค้นหา/, /^.{0,3}\s*เบิก$/, /รับคืน/, /Monitor/, /สรุป Stand By/, /รายงาน/]) {
      expect(screen.getAllByRole("link", { name }).length).toBeGreaterThan(0);
    }
  });
});
