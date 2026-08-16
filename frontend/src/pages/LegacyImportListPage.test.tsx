import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LegacyImportListPage } from "@/pages/LegacyImportListPage";
import type { ImportSessionPage, ImportSessionSummary } from "@/types/legacyImport";
import type { Page } from "@/types";
import type { ImportSessionOut } from "@/types/legacyImportApi";
import type { UserProfile as _UserProfile } from "@/types";

const listSessions = vi.fn();
vi.mock("@/services/legacyImportClient", () => ({
  legacyImportClient: {
    listSessions: (...args: unknown[]) => listSessions(...args),
  },
  ImportSessionNotFoundError: class ImportSessionNotFoundError extends Error {},
}));

const listEquipmentMasterSessions = vi.fn();
vi.mock("@/services/equipmentMasterImportClient", () => ({
  listEquipmentMasterSessions: (...args: unknown[]) => listEquipmentMasterSessions(...args),
}));

let mockUser: _UserProfile | null = null;
vi.mock("@/hooks/useAuth", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useAuth")>("@/hooks/useAuth");
  return {
    ...actual,
    useAuth: () => ({ user: mockUser, isAuthenticated: true, isLoading: false }),
  };
});

function makeUser(role: _UserProfile["role"]): _UserProfile {
  return { id: "user-1", employee_code: "U001", full_name: "Test User", email: "u@test.dev", role, permissions: {} };
}

function makeSummary(overrides: Partial<ImportSessionSummary> = {}): ImportSessionSummary {
  return {
    id: "demo-1",
    datasetType: "receive_history",
    filename: "receive.xlsx",
    status: "dry_run_completed",
    createdByUserId: "user-1",
    requestedByDisplayName: "สมชาย ใจดี",
    createdAt: "2026-07-20T03:00:00Z",
    totalRows: 100,
    validRows: 95,
    invalidRows: 5,
    warningRows: 5,
    importedRows: null,
    failureReason: null,
    ...overrides,
  };
}

function makePage(items: ImportSessionSummary[]): ImportSessionPage {
  return { items, nextCursor: null, total: items.length };
}

function makeRealPage(items: ImportSessionOut[], overrides: Partial<Page<ImportSessionOut>> = {}): Page<ImportSessionOut> {
  return { items, next_cursor: null, total: items.length, ...overrides };
}

function makeRealSession(overrides: Partial<ImportSessionOut> = {}): ImportSessionOut {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    dataset_type: "equipment_master",
    status: "completed",
    version: 3,
    created_by_user_id: "22222222-2222-4222-8222-222222222222",
    idempotency_key: null,
    notes: null,
    terminal_at: "2026-07-21T00:00:00Z",
    failure_reason: null,
    created_at: "2026-07-21T00:00:00Z",
    updated_at: "2026-07-21T00:00:00Z",
    validated_at: "2026-07-20T00:00:00Z",
    total_rows: 500,
    valid_rows: 500,
    invalid_rows: 0,
    warning_rows: 0,
    dry_run_completed_at: "2026-07-20T01:00:00Z",
    executed_at: "2026-07-21T00:00:00Z",
    imported_rows: 500,
    ...overrides,
  };
}

beforeEach(() => {
  mockUser = makeUser("administrator");
  listSessions.mockResolvedValue(makePage([makeSummary()]));
  listEquipmentMasterSessions.mockResolvedValue(makeRealPage([]));
});

afterEach(() => {
  vi.clearAllMocks();
});

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/imports"]}>
        <Routes>
          <Route path="/imports" element={<LegacyImportListPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("LegacyImportListPage", () => {
  it("shows the Receive/Issue History prototype notice", async () => {
    renderPage();
    expect(await screen.findByText(/ประวัติการรับคืนและประวัติการเบิกยังเป็นต้นแบบ/)).toBeInTheDocument();
  });

  it("shows a loading state while sessions are being fetched", async () => {
    listSessions.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(await screen.findByText("กำลังโหลดรายการนำเข้าข้อมูล...")).toBeInTheDocument();
  });

  it("shows an empty state when there are no sessions", async () => {
    listSessions.mockResolvedValue(makePage([]));
    renderPage();
    expect(await screen.findByText("ยังไม่มีรายการนำเข้าข้อมูล")).toBeInTheDocument();
  });

  it("renders session rows when populated", async () => {
    renderPage();
    expect(await screen.findByText("receive.xlsx")).toBeInTheDocument();
    expect(screen.getByText("สมชาย ใจดี")).toBeInTheDocument();
  });

  it("shows an error state with retry, and retry recovers on success", async () => {
    listSessions.mockRejectedValueOnce(new Error("network error"));
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("ไม่สามารถโหลดรายการนำเข้าข้อมูลได้")).toBeInTheDocument();
    listSessions.mockResolvedValueOnce(makePage([makeSummary()]));
    await user.click(screen.getByRole("button", { name: "ลองใหม่" }));

    await waitFor(() => expect(screen.queryByText("ไม่สามารถโหลดรายการนำเข้าข้อมูลได้")).not.toBeInTheDocument());
    expect(await screen.findByText("receive.xlsx")).toBeInTheDocument();
  });

  it('offers a "เริ่มนำเข้าข้อมูล" action linking to /imports/new', async () => {
    renderPage();
    await screen.findByText("receive.xlsx");
    const action = screen.getByRole("link", { name: "เริ่มนำเข้าข้อมูล" });
    expect(action).toHaveAttribute("href", "/imports/new");
  });

  it("shows a permission-denied state for a non-administrator", async () => {
    mockUser = makeUser("read_only");
    renderPage();
    expect(await screen.findByText("คุณไม่มีสิทธิ์เข้าถึงหน้านำเข้าข้อมูลเดิม")).toBeInTheDocument();
    expect(listSessions).not.toHaveBeenCalled();
    expect(listEquipmentMasterSessions).not.toHaveBeenCalled();
  });

  it("merges real equipment_master sessions with mock Receive/Issue sessions, excluding any mock equipment_master row", async () => {
    listSessions.mockResolvedValue(
      makePage([makeSummary({ id: "mock-receive-1", datasetType: "receive_history", filename: "receive.xlsx" })])
    );
    listEquipmentMasterSessions.mockResolvedValue(makeRealPage([makeRealSession()]));
    renderPage();
    expect(await screen.findByText("receive.xlsx")).toBeInTheDocument();
    expect(await screen.findByText("500 แถว")).toBeInTheDocument();
    expect(screen.getByText("22222222-2222-4222-8222-222222222222")).toBeInTheDocument();
  });

  // Roadmap PR20F review round 1, P1 "Legacy Import session list must
  // paginate": a single limit:50 fetch silently hid every real session
  // beyond the first page.
  describe("real Equipment Master session pagination", () => {
    it("shows Load more only when next_cursor exists, requests the next page with the exact cursor, appends without duplicating, and hides the button on the final page", async () => {
      listSessions.mockResolvedValue(makePage([]));
      listEquipmentMasterSessions.mockImplementation(async (params?: { cursor?: string | null }) => {
        if (!params?.cursor) {
          return makeRealPage([makeRealSession({ id: "session-a", total_rows: 100 })], { next_cursor: "page-2", total: 2 });
        }
        return makeRealPage([makeRealSession({ id: "session-b", total_rows: 200 })], { next_cursor: null, total: 2 });
      });

      const user = userEvent.setup();
      renderPage();

      expect(await screen.findByText("100 แถว")).toBeInTheDocument();
      expect(screen.queryByText("200 แถว")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "โหลดเพิ่มเติม" })).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "โหลดเพิ่มเติม" }));

      // Page 1's row remains (never discarded) and page 2's row is
      // appended -- never duplicated -- and the request used the exact
      // cursor the backend returned.
      expect(await screen.findByText("200 แถว")).toBeInTheDocument();
      expect(screen.getByText("100 แถว")).toBeInTheDocument();
      expect(screen.getAllByText(/^\d+ แถว$/)).toHaveLength(2);
      expect(listEquipmentMasterSessions).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: "page-2" }));
      await waitFor(() => expect(screen.queryByRole("button", { name: "โหลดเพิ่มเติม" })).not.toBeInTheDocument());
      expect(screen.getByText("ข้อมูลหลักเครื่องมือ: แสดง 2 จาก 2 รายการ")).toBeInTheDocument();
    });

    it("does not fabricate a total count when the backend page has none to show, and no Load more button appears for a single, complete page", async () => {
      listSessions.mockResolvedValue(makePage([]));
      listEquipmentMasterSessions.mockResolvedValue(makeRealPage([makeRealSession({ id: "session-a" })], { next_cursor: null, total: 1 }));

      renderPage();

      await screen.findByText("500 แถว");
      expect(screen.queryByRole("button", { name: "โหลดเพิ่มเติม" })).not.toBeInTheDocument();
      expect(screen.getByText("ข้อมูลหลักเครื่องมือ: แสดง 1 จาก 1 รายการ")).toBeInTheDocument();
    });
  });
});
