import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CutoverReadinessListPage } from "@/pages/CutoverReadinessListPage";
import type { Page, UserProfile } from "@/types";
import type { CutoverReadinessRunListItem } from "@/types/cutoverReadiness";

const fetchCutoverReadinessRuns = vi.fn();
vi.mock("@/services/cutoverReadiness", async () => {
  const actual = await vi.importActual<typeof import("@/services/cutoverReadiness")>("@/services/cutoverReadiness");
  return {
    ...actual,
    fetchCutoverReadinessRuns: (...args: unknown[]) => fetchCutoverReadinessRuns(...args),
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

function makeRun(overrides: Partial<CutoverReadinessRunListItem> = {}): CutoverReadinessRunListItem {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    status: "completed",
    version: 1,
    created_by_user_id: "22222222-2222-4222-8222-222222222222",
    created_at: "2026-07-01T00:00:00Z",
    completed_at: "2026-07-01T00:05:00Z",
    completed_by_user_id: "22222222-2222-4222-8222-222222222222",
    application_baseline_sha: "a".repeat(40),
    database_migration_head: "0022_cutover_go_no_go_decision",
    source_of_truth_strategy: "hard_cutover",
    cutover_instant: "2026-08-01T00:00:00Z",
    freeze_window_reference: null,
    supersedes_run_id: null,
    ...overrides,
  };
}

function makePage(items: CutoverReadinessRunListItem[]): Page<CutoverReadinessRunListItem> {
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
      <MemoryRouter initialEntries={["/cutover-readiness"]}>
        <Routes>
          <Route path="/cutover-readiness" element={<CutoverReadinessListPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("CutoverReadinessListPage", () => {
  it("shows a loading state while runs are being fetched", async () => {
    fetchCutoverReadinessRuns.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(await screen.findByText(/กำลังโหลดรายการ/)).toBeInTheDocument();
  });

  it("shows an error state with retry on failure", async () => {
    fetchCutoverReadinessRuns.mockRejectedValue(new Error("network down"));
    renderPage();
    await waitFor(() => expect(screen.getByText(/ไม่สามารถโหลดรายการความพร้อมก่อนเปลี่ยนระบบได้/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "ลองใหม่" })).toBeInTheDocument();
  });

  it("shows an empty state when there are no runs", async () => {
    fetchCutoverReadinessRuns.mockResolvedValue(makePage([]));
    renderPage();
    await waitFor(() => expect(screen.getByText(/ยังไม่มีรอบตรวจสอบความพร้อม/)).toBeInTheDocument());
  });

  it("renders run rows with Thai status label and supersession indicator", async () => {
    fetchCutoverReadinessRuns.mockResolvedValue(
      makePage([
        makeRun({ status: "completed" }),
        makeRun({ id: "run-2", status: "pending", supersedes_run_id: "11111111-1111-4111-8111-111111111111" }),
      ])
    );
    renderPage();
    await waitFor(() => expect(screen.getByText("บันทึกหลักฐานครบถ้วน")).toBeInTheDocument());
    expect(screen.getByText("รอดำเนินการ")).toBeInTheDocument();
    expect(screen.getByText("แทนที่รอบก่อนหน้า")).toBeInTheDocument();
  });

  it("is enabled/visible for every authenticated role (mirrors backend VIEW_AND_REPORT_ROLES)", async () => {
    mockUser = makeUser("read_only");
    fetchCutoverReadinessRuns.mockResolvedValue(makePage([]));
    renderPage();
    await waitFor(() => expect(fetchCutoverReadinessRuns).toHaveBeenCalled());
  });
});
