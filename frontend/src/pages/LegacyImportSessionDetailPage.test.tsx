import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LegacyImportSessionDetailPage } from "@/pages/LegacyImportSessionDetailPage";
import type { UserProfile } from "@/types";

const getImportSessionSummary = vi.fn();
vi.mock("@/services/importSessionClient", () => ({
  getImportSessionSummary: (...args: unknown[]) => getImportSessionSummary(...args),
}));

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

const SESSION_ID = "11111111-1111-4111-8111-111111111111";

function makeSummary(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: SESSION_ID,
    dataset_type: "equipment_master",
    status: "created",
    version: 1,
    created_by_user_id: "user-1",
    idempotency_key: null,
    notes: null,
    terminal_at: null,
    failure_reason: null,
    created_at: "2026-07-20T03:00:00Z",
    updated_at: "2026-07-20T03:00:00Z",
    validated_at: null,
    total_rows: null,
    valid_rows: null,
    invalid_rows: null,
    warning_rows: null,
    dry_run_completed_at: null,
    executed_at: null,
    imported_rows: null,
    jobs: [],
    finding_count: 0,
    validation_attempt_id: null,
    ...overrides,
  };
}

beforeEach(() => {
  mockUser = makeUser("administrator");
});

afterEach(() => {
  vi.resetAllMocks();
});

function renderPage(sessionId = SESSION_ID) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/imports/${sessionId}`]}>
        <Routes>
          <Route path="/imports/:sessionId" element={<LegacyImportSessionDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

// Roadmap PR21E (design §12): which panel renders is decided purely by the
// session's own real `dataset_type`, fetched once via the shared
// getImportSessionSummary seam -- never inferred from the route/id shape
// (the former PR19B/PR20F isBackendSessionId UUID-regex routing no longer
// exists; every session id on this route is real now).
describe("LegacyImportSessionDetailPage", () => {
  it("shows a loading state", async () => {
    getImportSessionSummary.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(await screen.findByText("กำลังโหลดรายละเอียดการนำเข้าข้อมูล...")).toBeInTheDocument();
  });

  it("routes an equipment_master session to the Equipment Master workflow panel", async () => {
    getImportSessionSummary.mockResolvedValue(makeSummary({ dataset_type: "equipment_master" }));
    renderPage();

    expect(await screen.findByText("นำเข้าข้อมูลหลักเครื่องมือ")).toBeInTheDocument();
    expect(getImportSessionSummary).toHaveBeenCalledWith(SESSION_ID);
  });

  it("routes a legacy_transaction_history session to the Legacy History workflow panel", async () => {
    getImportSessionSummary.mockResolvedValue(makeSummary({ dataset_type: "legacy_transaction_history" }));
    renderPage();

    expect(await screen.findByText("นำเข้าประวัติการรับ-ส่งเครื่องมือเดิม")).toBeInTheDocument();
  });

  it("renders correctly when loaded directly (no prior create-flow state)", async () => {
    getImportSessionSummary.mockResolvedValue(
      makeSummary({
        dataset_type: "legacy_transaction_history",
        status: "dry_run_completed",
        total_rows: 500,
        valid_rows: 500,
        invalid_rows: 0,
        warning_rows: 0,
      })
    );
    renderPage();

    expect(await screen.findByText("นำเข้าประวัติการรับ-ส่งเครื่องมือเดิม")).toBeInTheDocument();
    expect(screen.getByText(SESSION_ID, { exact: false })).toBeInTheDocument();
  });

  it("shows a safe unsupported-dataset state for an unrecognized dataset_type, never the Equipment Master panel", async () => {
    getImportSessionSummary.mockResolvedValue(makeSummary({ dataset_type: "something_unknown" }));
    renderPage();

    expect(await screen.findByText("ไม่รองรับประเภทข้อมูลนี้")).toBeInTheDocument();
    expect(screen.queryByText("นำเข้าข้อมูลหลักเครื่องมือ")).not.toBeInTheDocument();
    expect(screen.queryByText("นำเข้าประวัติการรับ-ส่งเครื่องมือเดิม")).not.toBeInTheDocument();
  });

  it("shows a not-found message for an unknown session id", async () => {
    const error = Object.assign(new Error("not found"), {
      isAxiosError: true,
      response: { status: 404, data: { code: "IMPORT_SESSION_NOT_FOUND", detail: "not found" } },
    });
    getImportSessionSummary.mockRejectedValue(error);
    renderPage("22222222-2222-4222-8222-222222222222");

    expect(await screen.findByText("ไม่พบรายการนำเข้าข้อมูลนี้")).toBeInTheDocument();
  });

  it("shows a generic error state with retry for a non-not-found failure", async () => {
    getImportSessionSummary.mockRejectedValue(new Error("network error"));
    renderPage();

    expect(await screen.findByText("ไม่สามารถโหลดรายละเอียดการนำเข้าข้อมูลได้")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ลองใหม่" })).toBeInTheDocument();
  });

  it("shows a permission-denied state for a non-administrator, and never calls the session client", async () => {
    mockUser = makeUser("read_only");
    renderPage();

    expect(await screen.findByText("คุณไม่มีสิทธิ์เข้าถึงหน้านำเข้าข้อมูลเดิม")).toBeInTheDocument();
    expect(getImportSessionSummary).not.toHaveBeenCalled();
  });
});
