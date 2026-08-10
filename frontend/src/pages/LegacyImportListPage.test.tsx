import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LegacyImportListPage } from "@/pages/LegacyImportListPage";
import type { ImportSessionPage, ImportSessionSummary } from "@/types/legacyImport";
import type { UserProfile as _UserProfile } from "@/types";

const listSessions = vi.fn();
vi.mock("@/services/legacyImportClient", () => ({
  legacyImportClient: {
    listSessions: (...args: unknown[]) => listSessions(...args),
  },
  ImportSessionNotFoundError: class ImportSessionNotFoundError extends Error {},
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
    validRows: 90,
    invalidRows: 5,
    warningRows: 5,
    importedRows: null,
    ...overrides,
  };
}

function makePage(items: ImportSessionSummary[]): ImportSessionPage {
  return { items, nextCursor: null, total: items.length };
}

beforeEach(() => {
  mockUser = makeUser("administrator");
  listSessions.mockResolvedValue(makePage([makeSummary()]));
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
  it("shows the skeleton indicator", async () => {
    renderPage();
    expect(await screen.findByText(/ต้นแบบหน้าจอ/)).toBeInTheDocument();
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
  });
});
