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
