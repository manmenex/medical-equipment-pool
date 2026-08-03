import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LegacyImportSessionDetailPage } from "@/pages/LegacyImportSessionDetailPage";
import { ImportSessionNotFoundError } from "@/services/legacyImportClient";
import type { ImportSessionDetail } from "@/types/legacyImport";
import type { UserProfile } from "@/types";

const getSession = vi.fn();

vi.mock("@/services/legacyImportClient", () => {
  class FakeImportSessionNotFoundError extends Error {}
  return {
    legacyImportClient: {
      getSession: (...args: unknown[]) => getSession(...args),
    },
    ImportSessionNotFoundError: FakeImportSessionNotFoundError,
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

function makeDetail(overrides: Partial<ImportSessionDetail> = {}): ImportSessionDetail {
  return {
    id: "demo-1",
    importCategory: "receive_history",
    filename: "receive.xlsx",
    status: "awaiting_confirmation",
    requestedByDisplayName: "สมชาย ใจดี",
    createdAt: "2026-07-20T03:00:00Z",
    totalRows: 100,
    importedCount: null,
    skippedCount: null,
    failedCount: null,
    requestedFileSizeBytes: 2048,
    validationSummary: {
      totalRows: 100,
      validRows: 90,
      warningRows: 5,
      invalidRows: 5,
      duplicateRows: 0,
      byCategory: [],
    },
    issues: [
      {
        rowNumber: 3,
        field: "วันที่",
        submittedValue: "bad",
        issueCode: "INVALID_DATE",
        explanationTh: "รูปแบบวันที่ไม่ถูกต้อง",
        severity: "error",
      },
    ],
    dryRunSummary: {
      wouldCreateCount: 90,
      wouldSkipCount: 5,
      duplicateCount: 0,
      validationFailureCount: 5,
      warningCount: 5,
    },
    resultSummary: null,
    ...overrides,
  };
}

beforeEach(() => {
  mockUser = makeUser("administrator");
});

afterEach(() => {
  vi.clearAllMocks();
});

function renderPage(sessionId = "demo-1") {
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

describe("LegacyImportSessionDetailPage", () => {
  it("shows a loading state", async () => {
    getSession.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(await screen.findByText("กำลังโหลดรายละเอียดการนำเข้าข้อมูล...")).toBeInTheDocument();
  });

  it("renders validation summary, issue rows, and dry-run summary with a disabled confirm action", async () => {
    getSession.mockResolvedValue(makeDetail());
    renderPage();

    expect(await screen.findByText("สรุปผลการตรวจสอบข้อมูล")).toBeInTheDocument();
    // Rendered twice -- once in the desktop table, once in the mobile card
    // fallback (task brief: "responsive tables or card fallback on small
    // screens") -- jsdom has no viewport, so both are present in the DOM.
    expect(screen.getAllByText("รูปแบบวันที่ไม่ถูกต้อง").length).toBeGreaterThan(0);
    expect(screen.getByText("สรุปผลทดลองนำเข้าโดยไม่บันทึก")).toBeInTheDocument();

    const confirmButton = screen.getByRole("button", { name: /ยืนยันนำเข้า/ });
    expect(confirmButton).toBeDisabled();
  });

  it("renders a result summary for a completed session and no dry-run confirm action", async () => {
    getSession.mockResolvedValue(
      makeDetail({
        status: "completed",
        resultSummary: {
          status: "completed",
          importedCount: 90,
          skippedCount: 5,
          failedCount: 0,
          completedAt: "2026-07-20T04:00:00Z",
          sessionReference: "demo-1",
        },
      })
    );
    renderPage();

    expect(await screen.findByText("สรุปผลการนำเข้า")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /ยืนยันนำเข้า/ })).not.toBeInTheDocument();
  });

  it("shows a not-found message for an unknown session id", async () => {
    getSession.mockRejectedValue(new ImportSessionNotFoundError("nope"));
    renderPage("does-not-exist");

    expect(await screen.findByText("ไม่พบรายการนำเข้าข้อมูลนี้")).toBeInTheDocument();
  });

  it("shows a generic error state with retry for a non-not-found failure", async () => {
    getSession.mockRejectedValue(new Error("network error"));
    renderPage();

    expect(await screen.findByText("ไม่สามารถโหลดรายละเอียดการนำเข้าข้อมูลได้")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ลองใหม่" })).toBeInTheDocument();
  });

  it("shows a permission-denied state for a non-administrator and never calls getSession", async () => {
    mockUser = makeUser("read_only");
    renderPage();

    expect(await screen.findByText("คุณไม่มีสิทธิ์เข้าถึงหน้านำเข้าข้อมูลเดิม")).toBeInTheDocument();
    expect(getSession).not.toHaveBeenCalled();
  });
});
