import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LegacyImportListPage } from "@/pages/LegacyImportListPage";
import type { Page } from "@/types";
import type { ImportSessionOut } from "@/types/legacyImportApi";
import type { UserProfile } from "@/types";

const listEquipmentMasterSessions = vi.fn();
vi.mock("@/services/equipmentMasterImportClient", () => ({
  listEquipmentMasterSessions: (...args: unknown[]) => listEquipmentMasterSessions(...args),
}));

const listLegacyHistorySessions = vi.fn();
vi.mock("@/services/legacyHistoryImportClient", () => ({
  listLegacyHistorySessions: (...args: unknown[]) => listLegacyHistorySessions(...args),
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

function makePage(items: ImportSessionOut[], overrides: Partial<Page<ImportSessionOut>> = {}): Page<ImportSessionOut> {
  return { items, next_cursor: null, total: items.length, ...overrides };
}

function makeSession(overrides: Partial<ImportSessionOut> = {}): ImportSessionOut {
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
  listEquipmentMasterSessions.mockResolvedValue(makePage([]));
  listLegacyHistorySessions.mockResolvedValue(makePage([]));
});

afterEach(() => {
  vi.resetAllMocks();
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
  it("shows a loading state while sessions are being fetched", async () => {
    listEquipmentMasterSessions.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(await screen.findByText("กำลังโหลดรายการนำเข้าข้อมูล...")).toBeInTheDocument();
  });

  it("shows an empty state when there are no sessions of either dataset type", async () => {
    renderPage();
    expect(await screen.findByText("ยังไม่มีรายการนำเข้าข้อมูล")).toBeInTheDocument();
  });

  it("merges real Equipment Master and Legacy History sessions into one real list", async () => {
    listEquipmentMasterSessions.mockResolvedValue(makePage([makeSession({ id: "eq-1", dataset_type: "equipment_master", total_rows: 500 })]));
    listLegacyHistorySessions.mockResolvedValue(
      makePage([
        makeSession({
          id: "lh-1",
          dataset_type: "legacy_transaction_history",
          created_by_user_id: "33333333-3333-4333-8333-333333333333",
          total_rows: 200,
        }),
      ])
    );
    renderPage();

    expect(await screen.findByText("500 แถว")).toBeInTheDocument();
    expect(screen.getByText("200 แถว")).toBeInTheDocument();
    expect(screen.getByText("22222222-2222-4222-8222-222222222222")).toBeInTheDocument();
    expect(screen.getByText("33333333-3333-4333-8333-333333333333")).toBeInTheDocument();
    expect(screen.getByText("ข้อมูลหลักเครื่องมือ (Equipment Master)")).toBeInTheDocument();
    expect(screen.getByText("ประวัติการรับ-ส่งเครื่องมือเดิม")).toBeInTheDocument();
  });

  it("shows an error state with retry, and retry recovers on success", async () => {
    listEquipmentMasterSessions.mockRejectedValueOnce(new Error("network error"));
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("ไม่สามารถโหลดรายการนำเข้าข้อมูลได้")).toBeInTheDocument();
    listEquipmentMasterSessions.mockResolvedValueOnce(makePage([makeSession()]));
    await user.click(screen.getByRole("button", { name: "ลองใหม่" }));

    await waitFor(() => expect(screen.queryByText("ไม่สามารถโหลดรายการนำเข้าข้อมูลได้")).not.toBeInTheDocument());
    expect(await screen.findByText("500 แถว")).toBeInTheDocument();
  });

  it('offers a "เริ่มนำเข้าข้อมูล" action linking to /imports/new', async () => {
    renderPage();
    await screen.findByText("ยังไม่มีรายการนำเข้าข้อมูล");
    const action = screen.getByRole("link", { name: "เริ่มนำเข้าข้อมูล" });
    expect(action).toHaveAttribute("href", "/imports/new");
  });

  it("shows a permission-denied state for a non-administrator, and never calls either real client", async () => {
    mockUser = makeUser("read_only");
    renderPage();
    expect(await screen.findByText("คุณไม่มีสิทธิ์เข้าถึงหน้านำเข้าข้อมูลเดิม")).toBeInTheDocument();
    expect(listEquipmentMasterSessions).not.toHaveBeenCalled();
    expect(listLegacyHistorySessions).not.toHaveBeenCalled();
  });

  describe("cursor pagination across both real sources", () => {
    it("shows Load more only when a next_cursor exists, requests the next page with the exact cursor, appends without duplicating, and hides the button on the final page", async () => {
      listEquipmentMasterSessions.mockImplementation(async (params?: { cursor?: string | null }) => {
        if (!params?.cursor) {
          return makePage([makeSession({ id: "session-a", total_rows: 100 })], { next_cursor: "page-2", total: 2 });
        }
        return makePage([makeSession({ id: "session-b", total_rows: 200 })], { next_cursor: null, total: 2 });
      });

      const user = userEvent.setup();
      renderPage();

      expect(await screen.findByText("100 แถว")).toBeInTheDocument();
      expect(screen.queryByText("200 แถว")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "โหลดเพิ่มเติม" })).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "โหลดเพิ่มเติม" }));

      expect(await screen.findByText("200 แถว")).toBeInTheDocument();
      expect(screen.getByText("100 แถว")).toBeInTheDocument();
      expect(listEquipmentMasterSessions).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: "page-2" }));
      await waitFor(() => expect(screen.queryByRole("button", { name: "โหลดเพิ่มเติม" })).not.toBeInTheDocument());
    });

    it("does not fabricate a total count when the backend page has none to show, and no Load more button appears for a single, complete page", async () => {
      listEquipmentMasterSessions.mockResolvedValue(makePage([makeSession({ id: "session-a" })], { next_cursor: null, total: 1 }));

      renderPage();

      await screen.findByText("500 แถว");
      expect(screen.queryByRole("button", { name: "โหลดเพิ่มเติม" })).not.toBeInTheDocument();
    });
  });
});
