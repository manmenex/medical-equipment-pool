import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LegacyImportSessionDetailPage } from "@/pages/LegacyImportSessionDetailPage";
import { ImportSessionNotFoundError } from "@/services/legacyImportClient";
import type { ImportSessionDetail } from "@/types/legacyImport";
import type { UserProfile } from "@/types";
import { assertImportSessionInvariants } from "@/utils/legacyImportInvariants";

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

const getEquipmentMasterSession = vi.fn();
vi.mock("@/services/equipmentMasterImportClient", () => ({
  getEquipmentMasterSession: (...args: unknown[]) => getEquipmentMasterSession(...args),
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

// Matches backend/app/schemas/import_session.py's ImportSessionOut field-for-
// field where a real field exists; findings mirror ValidationFindingOut
// (id/row_number/field/error_code/message/severity).
//
// Default status is dry_run_completed (the real confirm-gate state, design
// §5), which is reachable only from VALIDATED -- so, per design §12/§13,
// invalidRows must be 0 and the finding below is warning-severity, not
// error. `assertImportSessionInvariants` runs on every call so an override
// that accidentally recreates an impossible combination fails the test
// immediately rather than silently rendering a state the real backend
// could never produce.
function makeDetail(overrides: Partial<ImportSessionDetail> = {}): ImportSessionDetail {
  const detail: ImportSessionDetail = {
    id: "demo-1",
    datasetType: "receive_history",
    filename: "receive.xlsx",
    status: "dry_run_completed",
    createdByUserId: "user-1",
    requestedByDisplayName: "สมชาย ใจดี",
    createdAt: "2026-07-20T03:00:00Z",
    totalRows: 100,
    validRows: 100,
    invalidRows: 0,
    warningRows: 1,
    importedRows: null,
    failureReason: null,
    requestedFileSizeBytes: 2048,
    validationCounts: {
      totalRows: 100,
      validRows: 100,
      warningRows: 1,
      invalidRows: 0,
    },
    findingsByCategory: [{ categoryLabelTh: "รูปแบบวันที่ไม่ถูกต้อง", count: 1 }],
    findings: [
      {
        id: "finding-1",
        rowNumber: 3,
        field: "วันที่",
        errorCode: "INVALID_DATE",
        message: "รูปแบบวันที่ไม่ถูกต้อง",
        severity: "warning",
      },
    ],
    resultSummary: null,
    ...overrides,
  };
  assertImportSessionInvariants(detail);
  return detail;
}

const REAL_SESSION_ID = "11111111-1111-4111-8111-111111111111";

function makeRealSummary(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: REAL_SESSION_ID,
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

  it("renders validation summary, finding rows, and the dry-run confirm-gate panel with a disabled confirm action", async () => {
    getSession.mockResolvedValue(makeDetail());
    renderPage();

    expect(await screen.findByText("สรุปผลการตรวจสอบข้อมูล")).toBeInTheDocument();
    // Rendered twice -- once in the desktop table, once in the mobile card
    // fallback (task brief: "responsive tables or card fallback on small
    // screens") -- jsdom has no viewport, so both are present in the DOM.
    expect(screen.getAllByText("รูปแบบวันที่ไม่ถูกต้อง").length).toBeGreaterThan(0);
    // Real backend confirm-gate status (design §5): dry_run_completed.
    expect(screen.getByText("ทดลองนำเข้าโดยไม่บันทึกแล้ว — รอการยืนยัน")).toBeInTheDocument();

    const confirmButton = screen.getByRole("button", { name: /ยืนยันนำเข้า/ });
    expect(confirmButton).toBeDisabled();
  });

  it("shows the non-blocking warning note when warningRows > 0", async () => {
    getSession.mockResolvedValue(makeDetail());
    renderPage();

    expect(await screen.findByText(/คำเตือนไม่ปิดกั้นการดำเนินการต่อ/)).toBeInTheDocument();
  });

  it("does not show the dry-run confirm-gate panel for a status other than dry_run_completed", async () => {
    getSession.mockResolvedValue(makeDetail({ status: "validated" }));
    renderPage();

    await screen.findByText("สรุปผลการตรวจสอบข้อมูล");
    expect(screen.queryByText("ทดลองนำเข้าโดยไม่บันทึกแล้ว — รอการยืนยัน")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /ยืนยันนำเข้า/ })).not.toBeInTheDocument();
  });

  it("renders a result summary for a completed session and no dry-run confirm action", async () => {
    getSession.mockResolvedValue(
      makeDetail({
        status: "completed",
        warningRows: 0,
        validationCounts: null,
        findingsByCategory: [],
        findings: [],
        resultSummary: {
          status: "completed",
          importedRows: 90,
          terminalAt: "2026-07-20T04:00:00Z",
          sessionId: "demo-1",
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

  // Roadmap PR20F design §41 "category dispatch" + "reload" tests: a UUID
  // session id routes to the real EquipmentMasterWorkflowPanel (and its own
  // real API client) instead of the PR19B mock view -- purely from the
  // session id shape in the URL, with no reliance on any prior in-memory
  // navigation state (design §39: a direct reload/URL visit must recover
  // fully from backend truth).
  describe("real Equipment Master session (UUID id)", () => {
    it("routes a UUID session id to the real workflow panel, never the mock client", async () => {
      getEquipmentMasterSession.mockResolvedValue(makeRealSummary());
      renderPage(REAL_SESSION_ID);

      expect(await screen.findByText("นำเข้าข้อมูลหลักเครื่องมือ")).toBeInTheDocument();
      expect(getEquipmentMasterSession).toHaveBeenCalledWith(REAL_SESSION_ID);
      expect(getSession).not.toHaveBeenCalled();
    });

    it("renders correctly when the UUID route is loaded directly (no prior create-flow state)", async () => {
      getEquipmentMasterSession.mockResolvedValue(
        makeRealSummary({ status: "dry_run_completed", total_rows: 500, valid_rows: 500, invalid_rows: 0, warning_rows: 0 })
      );
      renderPage(REAL_SESSION_ID);

      expect(await screen.findByText("นำเข้าข้อมูลหลักเครื่องมือ")).toBeInTheDocument();
      expect(screen.getByText(REAL_SESSION_ID, { exact: false })).toBeInTheDocument();
    });

    it("shows a permission-denied state for a non-administrator on a real session id, and never calls the real client", async () => {
      mockUser = makeUser("read_only");
      renderPage(REAL_SESSION_ID);

      expect(await screen.findByText("คุณไม่มีสิทธิ์เข้าถึงหน้านำเข้าข้อมูลเดิม")).toBeInTheDocument();
      expect(getEquipmentMasterSession).not.toHaveBeenCalled();
    });
  });
});
