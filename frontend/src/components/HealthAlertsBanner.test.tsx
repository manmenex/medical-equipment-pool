import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HealthAlertsBanner } from "@/components/HealthAlertsBanner";
import type { UserProfile } from "@/types";

const fetchHealthAlerts = vi.fn();
vi.mock("@/services/system", () => ({ fetchHealthAlerts: () => fetchHealthAlerts() }));

let mockUser: UserProfile | null = null;
vi.mock("@/hooks/useAuth", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useAuth")>("@/hooks/useAuth");
  return { ...actual, useAuth: () => ({ user: mockUser, isAuthenticated: true, isLoading: false }) };
});

function makeUser(role: UserProfile["role"]): UserProfile {
  return { id: "u1", employee_code: "U001", full_name: "T", email: "u@test.dev", role, permissions: {}, must_change_password: false };
}

function renderBanner() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <HealthAlertsBanner />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

afterEach(() => vi.clearAllMocks());

describe("HealthAlertsBanner", () => {
  it("shows Thai alerts with a link for administrators", async () => {
    mockUser = makeUser("administrator");
    fetchHealthAlerts.mockResolvedValue([
      { code: "sync_review_queue", severity: "warning", message_th: "มีรายการซิงก์รอตรวจสอบ 3 รายการ", since: null },
    ]);
    renderBanner();
    expect(await screen.findByText("มีรายการซิงก์รอตรวจสอบ 3 รายการ")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "ดูรายละเอียด" })).toHaveAttribute("href", "/sync-review");
  });

  it("is hidden when the list is empty", async () => {
    mockUser = makeUser("administrator");
    fetchHealthAlerts.mockResolvedValue([]);
    renderBanner();
    await waitFor(() => expect(fetchHealthAlerts).toHaveBeenCalled());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("is hidden and never fetches for non-administrators", async () => {
    mockUser = makeUser("equipment_pool_staff");
    fetchHealthAlerts.mockResolvedValue([{ code: "sync_stale", severity: "warning", message_th: "x", since: null }]);
    renderBanner();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(fetchHealthAlerts).not.toHaveBeenCalled();
  });
});
