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
  return { id: "user-1", employee_code: "U001", full_name: "Test User", email: "u@test.dev", role, permissions: {} };
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

describe("AppShell legacy import nav entry", () => {
  it("shows the นำเข้าข้อมูลเดิม nav link for an administrator", () => {
    mockUser = makeUser("administrator");
    renderShell();

    expect(screen.getAllByRole("link", { name: /นำเข้าข้อมูลเดิม/ }).length).toBeGreaterThan(0);
  });

  // Bug-fix regression: the desktop sidebar's navItems array structurally
  // never included admin-tier entries in the mobile bottom nav -- the
  // mobile <nav> only ever mapped over navItems. Fixed by adding a
  // dedicated canManageLegacyImport-gated link to the mobile <nav> block,
  // mirroring the desktop sidebar's. This asserts both surfaces render
  // exactly one link each (desktop <aside> + mobile <nav>), not just "at
  // least one", so a regression that only fixes one surface fails loudly.
  it("reaches /imports from both the desktop sidebar and the mobile bottom nav for an administrator", () => {
    mockUser = makeUser("administrator");
    renderShell();

    const links = screen.getAllByRole("link", { name: /นำเข้าข้อมูลเดิม/ });
    expect(links).toHaveLength(2);
    for (const link of links) {
      expect(link).toHaveAttribute("href", "/imports");
    }
  });

  it("hides the นำเข้าข้อมูลเดิม nav link for equipment_pool_staff", () => {
    mockUser = makeUser("equipment_pool_staff");
    renderShell();

    expect(screen.queryByRole("link", { name: /นำเข้าข้อมูลเดิม/ })).not.toBeInTheDocument();
  });

  it("hides the นำเข้าข้อมูลเดิม nav link for read_only", () => {
    mockUser = makeUser("read_only");
    renderShell();

    expect(screen.queryByRole("link", { name: /นำเข้าข้อมูลเดิม/ })).not.toBeInTheDocument();
  });
});

// Roadmap PR22F §7/§37 of the task: unlike นำเข้าข้อมูลเดิม (Administrator-only,
// shown on both the desktop sidebar and the mobile bottom nav), the
// reconciliation entry is visible to every authenticated role (mirrors
// backend VIEW_AND_REPORT_ROLES) but deliberately reaches mobile users
// through the always-visible header row instead of the bottom nav, so it
// never competes for space with ค้นหา/เบิก/รับคืน/รายงาน. This asserts
// exactly two links (desktop sidebar + header), never a third link
// added to the mobile bottom-nav <nav> block.
describe("AppShell reconciliation nav entry", () => {
  it.each(["administrator", "equipment_pool_staff", "read_only"] as const)(
    "shows the ตรวจสอบข้อมูลย้อนหลัง link (sidebar + header, never bottom nav) for %s",
    (role) => {
      mockUser = makeUser(role);
      renderShell();

      const links = screen.getAllByRole("link", { name: /ตรวจสอบข้อมูลย้อนหลัง/ });
      expect(links).toHaveLength(2);
      for (const link of links) {
        expect(link).toHaveAttribute("href", "/reconciliation");
      }
    }
  );
});

// Roadmap PR23E: same placement rationale/assertion shape as the
// reconciliation nav entry directly above -- visible to every
// authenticated role (mirrors backend VIEW_AND_REPORT_ROLES, see
// hooks/useAuth.ts's canReviewCutoverReadiness), sidebar + header only,
// never the mobile bottom nav.
describe("AppShell cutover readiness nav entry", () => {
  it.each(["administrator", "equipment_pool_staff", "read_only"] as const)(
    "shows the ความพร้อมก่อนเปลี่ยนระบบ link (sidebar + header, never bottom nav) for %s",
    (role) => {
      mockUser = makeUser(role);
      renderShell();

      const links = screen.getAllByRole("link", { name: /ความพร้อมก่อนเปลี่ยนระบบ/ });
      expect(links).toHaveLength(2);
      for (const link of links) {
        expect(link).toHaveAttribute("href", "/cutover-readiness");
      }
    }
  );
});
