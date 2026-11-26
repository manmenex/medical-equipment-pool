import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "@/layouts/AppShell";
import type { UserProfile } from "@/types";

const fetchSyncConflicts = vi.fn();
vi.mock("@/services/syncReview", () => ({ fetchSyncConflicts: (...a: unknown[]) => fetchSyncConflicts(...a) }));

let mockUser: UserProfile | null = null;
vi.mock("@/hooks/useAuth", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useAuth")>("@/hooks/useAuth");
  return { ...actual, useAuth: () => ({ user: mockUser, isAuthenticated: true, isLoading: false }) };
});

function makeUser(role: UserProfile["role"]): UserProfile {
  return { id: "u1", employee_code: "U001", full_name: "T", email: "u@test.dev", role, permissions: {}, must_change_password: false };
}

function renderShell() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<div>home</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AppShell sync review badge on ตั้งค่า", () => {
  beforeEach(() => {
    fetchSyncConflicts.mockReset().mockResolvedValue({ total: 3, limit: 1, offset: 0, items: [] });
  });

  it("shows the pending count on the ตั้งค่า sidebar item for pool staff", async () => {
    mockUser = makeUser("equipment_pool_staff");
    renderShell();
    expect(await screen.findByLabelText("รอตรวจสอบ 3 รายการ")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /ตรวจสอบรายการออฟไลน์/ })).not.toBeInTheDocument();
  });

  it("hides the badge when the count is zero", async () => {
    fetchSyncConflicts.mockResolvedValue({ total: 0, limit: 1, offset: 0, items: [] });
    mockUser = makeUser("equipment_pool_staff");
    renderShell();
    await vi.waitFor(() => expect(fetchSyncConflicts).toHaveBeenCalled());
    expect(screen.queryByLabelText(/รอตรวจสอบ/)).not.toBeInTheDocument();
  });

  it("makes no request and shows no badge for read-only users", () => {
    mockUser = makeUser("read_only");
    renderShell();
    expect(screen.queryByLabelText(/รอตรวจสอบ/)).not.toBeInTheDocument();
    expect(fetchSyncConflicts).not.toHaveBeenCalled();
  });
});
