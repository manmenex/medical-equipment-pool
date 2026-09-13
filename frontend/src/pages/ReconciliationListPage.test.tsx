import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReconciliationListPage } from "@/pages/ReconciliationListPage";
import type { Page } from "@/types";
import type { ReconciliationRunListItem } from "@/types/reconciliation";
import type { UserProfile } from "@/types";

const fetchReconciliationRuns = vi.fn();
vi.mock("@/services/reconciliation", async () => {
  const actual = await vi.importActual<typeof import("@/services/reconciliation")>("@/services/reconciliation");
  return {
    ...actual,
    fetchReconciliationRuns: (...args: unknown[]) => fetchReconciliationRuns(...args),
  };
});

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

function makeRun(overrides: Partial<ReconciliationRunListItem> = {}): ReconciliationRunListItem {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    status: "completed",
    version: 0,
    rule_version: "pr22-v1",
    snapshot_as_of: "2026-07-01T00:00:00Z",
    created_by_user_id: "22222222-2222-4222-8222-222222222222",
    created_at: "2026-07-01T00:00:00Z",
    started_at: "2026-07-01T00:00:00Z",
    completed_at: "2026-07-01T00:05:00Z",
    failed_at: null,
    legacy_coverage_start: "2020-01-01T00:00:00Z",
    legacy_coverage_end: "2024-12-31T00:00:00Z",
    live_system_start: "2025-01-01T00:00:00Z",
    summary_total_findings: 10,
    summary_high: 2,
    summary_medium: 3,
    summary_low: 5,
    has_signoff: false,
    ...overrides,
  };
}

function makePage(items: ReconciliationRunListItem[]): Page<ReconciliationRunListItem> {
  return { items, next_cursor: null, total: items.length };
}

beforeEach(() => {
  mockUser = makeUser("administrator");
});

afterEach(() => {
  vi.resetAllMocks();
});

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/reconciliation"]}>
        <Routes>
          <Route path="/reconciliation" element={<ReconciliationListPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("ReconciliationListPage", () => {
  it("shows a loading state while runs are being fetched", async () => {
    fetchReconciliationRuns.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(await screen.findByText(/กำลังโหลดรายการตรวจสอบข้อมูล/)).toBeInTheDocument();
  });

  it("shows an error state with retry on failure", async () => {
    fetchReconciliationRuns.mockRejectedValue(new Error("network down"));
    renderPage();
    await waitFor(() => expect(screen.getByText(/ไม่สามารถโหลดรายการตรวจสอบข้อมูลได้/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "ลองใหม่" })).toBeInTheDocument();
  });

  it("shows an empty state when there are no runs", async () => {
    fetchReconciliationRuns.mockResolvedValue(makePage([]));
    renderPage();
    await waitFor(() => expect(screen.getByText(/ยังไม่มีรอบการตรวจสอบข้อมูล/)).toBeInTheDocument());
  });

  it("renders run rows with Thai status label and sign-off indicator", async () => {
    fetchReconciliationRuns.mockResolvedValue(
      makePage([makeRun({ status: "completed", has_signoff: true }), makeRun({ id: "run-2", status: "pending", has_signoff: false })])
    );
    renderPage();
    await waitFor(() => expect(screen.getByText("ประมวลผลเสร็จ")).toBeInTheDocument());
    expect(screen.getByText("รอประมวลผล")).toBeInTheDocument();
    expect(screen.getByText("ลงนามยืนยันแล้ว")).toBeInTheDocument();
  });

  it("is enabled/visible for every authenticated role (mirrors backend VIEW_AND_REPORT_ROLES)", async () => {
    mockUser = makeUser("read_only");
    fetchReconciliationRuns.mockResolvedValue(makePage([]));
    renderPage();
    await waitFor(() => expect(fetchReconciliationRuns).toHaveBeenCalled());
  });
});
