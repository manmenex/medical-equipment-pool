import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminPage } from "@/pages/AdminPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { EquipmentDetailPage } from "@/pages/EquipmentDetailPage";
import { EquipmentListPage } from "@/pages/EquipmentListPage";
import { MonitorPage } from "@/pages/MonitorPage";
import type { MonitorEvent } from "@/services/monitor";
import type { Equipment, UserProfile } from "@/types";

// Roadmap PR33 (D14): source filter/badges on the dashboard, equipment list/detail
// and Monitor; administrator "คืนผู้ให้ยืม" with confirm; admin batch tab visibility.

const fetchSummary = vi.fn();
const searchEquipment = vi.fn();
const getEquipment = vi.fn();
const getEquipmentHistory = vi.fn();
const returnToOwner = vi.fn();
const listTransactions = vi.fn();
const fetchMonitorEvents = vi.fn();

vi.mock("@/services/dashboard", () => ({ fetchSummary: (...a: unknown[]) => fetchSummary(...a) }));
vi.mock("@/services/equipment", () => ({
  searchEquipment: (...a: unknown[]) => searchEquipment(...a),
  getEquipment: (...a: unknown[]) => getEquipment(...a),
  getEquipmentHistory: (...a: unknown[]) => getEquipmentHistory(...a),
  returnToOwner: (...a: unknown[]) => returnToOwner(...a),
  createEquipment: vi.fn(),
  registerDemoLoanBatch: vi.fn(),
}));
vi.mock("@/services/borrow", () => ({
  listTransactions: (...a: unknown[]) => listTransactions(...a),
  correctTransactionWard: vi.fn(),
  getTransaction: vi.fn(),
  revealHn: vi.fn(),
  WARD_CORRECTION_REASON_MAX_LENGTH: 500,
}));
vi.mock("@/services/masterData", () => ({
  listWards: () => Promise.resolve([]),
  listCategories: () => Promise.resolve([]),
  listDepartments: () => Promise.resolve([]),
  listLocations: () => Promise.resolve([]),
  updateWardPhone: vi.fn(),
  updateDepartmentPhone: vi.fn(),
}));
vi.mock("@/services/monitor", () => ({ fetchMonitorEvents: (...a: unknown[]) => fetchMonitorEvents(...a) }));
vi.mock("@/services/cuffs", () => ({
  getOutstandingCuffs: () => Promise.resolve({ total_outstanding: 0, items: [] }),
}));

let mockUser: UserProfile | null = null;
vi.mock("@/hooks/useAuth", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useAuth")>("@/hooks/useAuth");
  return { ...actual, useAuth: () => ({ user: mockUser, isAuthenticated: true, isLoading: false }) };
});

function makeUser(role: UserProfile["role"]): UserProfile {
  return { id: "u1", employee_code: "U1", full_name: "T", email: "t@t.dev", role, permissions: {}, must_change_password: false };
}

function eq(over: Partial<Equipment> = {}): Equipment {
  return {
    id: "eq-d1",
    asset_number: null,
    serial_number: null,
    equipment_name: "Demo Pump",
    category_id: null,
    brand: "Acme",
    model: "X1",
    department_owner_id: null,
    current_location_id: null,
    status: "available_at_pool",
    bcm_code: "SN-100",
    pm_due_date: null,
    cal_due_date: null,
    created_at: "",
    updated_at: "",
    equipment_source: "demo",
    owner_company: "Acme Co.",
    due_back_date: "2026-12-31",
    has_charger: true,
    has_clamp: false,
    returned_to_owner_at: null,
    ...over,
  };
}

function wrap(ui: React.ReactElement, entry = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockUser = makeUser("administrator");
  fetchSummary.mockResolvedValue({ total: 3, available_at_pool: 2, issued_to_ward: 1, unavailable_defective: 0, decommissioned: 0 });
  searchEquipment.mockResolvedValue({ items: [], next_cursor: null, total: 0 });
  getEquipmentHistory.mockResolvedValue([]);
  listTransactions.mockResolvedValue({ items: [], next_cursor: null, total: 0 });
});
afterEach(() => vi.clearAllMocks());

describe("dashboard source filter chips", () => {
  it("defaults to all and refetches the summary with the chosen source", async () => {
    wrap(<DashboardPage />);
    await waitFor(() => expect(fetchSummary).toHaveBeenCalledWith("all"));
    const chips = screen.getByRole("group", { name: "ประเภทเครื่อง" });
    expect(within(chips).getByRole("button", { name: "ทั้งหมด" })).toHaveAttribute("aria-pressed", "true");

    await userEvent.click(within(chips).getByRole("button", { name: "Demo" }));
    await waitFor(() => expect(fetchSummary).toHaveBeenCalledWith("demo"));
    expect(within(chips).getByRole("button", { name: "Demo" })).toHaveAttribute("aria-pressed", "true");

    await userEvent.click(within(chips).getByRole("button", { name: "ยืม" }));
    await waitFor(() => expect(fetchSummary).toHaveBeenCalledWith("loan"));
    await userEvent.click(within(chips).getByRole("button", { name: "Pool" }));
    await waitFor(() => expect(fetchSummary).toHaveBeenCalledWith("pool"));
  });
});

describe("equipment list", () => {
  it("shows source badges and the serial for demo/loan rows", async () => {
    searchEquipment.mockResolvedValue({
      items: [eq(), eq({ id: "eq-p", equipment_name: "Pool Pump", equipment_source: "pool", asset_number: "AST-1", bcm_code: "BCM1" })],
      next_cursor: null,
      total: 2,
    });
    wrap(<EquipmentListPage />);
    await screen.findByText("Demo Pump");
    expect(screen.getAllByTestId("source-badge")).toHaveLength(1);
    expect(screen.getByText(/SN SN-100/)).toBeInTheDocument();
    expect(screen.getByText("AST-1")).toBeInTheDocument();
  });

  it("filters by source and can include returned devices", async () => {
    wrap(<EquipmentListPage />);
    await waitFor(() => expect(searchEquipment).toHaveBeenCalled());
    await userEvent.selectOptions(screen.getByLabelText("ประเภทเครื่อง"), "loan");
    await waitFor(() => expect(searchEquipment).toHaveBeenLastCalledWith(expect.objectContaining({ source: "loan" })));
    await userEvent.click(screen.getByLabelText("แสดงที่คืนผู้ให้ยืมแล้ว"));
    await waitFor(() =>
      expect(searchEquipment).toHaveBeenLastCalledWith(expect.objectContaining({ source: "loan", include_returned: true })),
    );
  });

  it("marks returned devices", async () => {
    searchEquipment.mockResolvedValue({
      items: [eq({ returned_to_owner_at: "2026-11-26T00:00:00Z" })],
      next_cursor: null,
      total: 1,
    });
    wrap(<EquipmentListPage />, "/equipment?include_returned=true");
    expect(await screen.findByText(/คืนผู้ให้ยืมแล้ว/, { selector: "div" })).toBeInTheDocument();
  });
});

function renderDetail() {
  return wrap(
    <Routes>
      <Route path="/equipment/:id" element={<EquipmentDetailPage />} />
    </Routes>,
    "/equipment/eq-d1",
  );
}

describe("equipment detail: badge and return to owner", () => {
  it("shows the badge, owner company, due date and accessory presence", async () => {
    getEquipment.mockResolvedValue(eq());
    renderDetail();
    await screen.findByRole("heading", { name: /Demo Pump/ });
    expect(screen.getByTestId("source-badge")).toHaveTextContent("DEMO");
    const info = screen.getByLabelText("ข้อมูล Demo/ยืม");
    expect(within(info).getByText("Acme Co.")).toBeInTheDocument();
    expect(within(info).getByText("2026-12-31")).toBeInTheDocument();
    expect(within(info).getByText(/มีสายชาร์จ · ไม่มี Clamp/)).toBeInTheDocument();
  });

  it("asks for confirmation, then returns the device to its owner", async () => {
    getEquipment.mockResolvedValue(eq());
    returnToOwner.mockResolvedValue(eq({ returned_to_owner_at: "2026-11-26T00:00:00Z" }));
    renderDetail();
    await userEvent.click(await screen.findByRole("button", { name: "คืนผู้ให้ยืม" }));
    expect(returnToOwner).not.toHaveBeenCalled();
    const dialog = screen.getByRole("alertdialog", { name: "ยืนยันคืนผู้ให้ยืม" });

    await userEvent.click(within(dialog).getByRole("button", { name: "ยกเลิก" }));
    expect(returnToOwner).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "คืนผู้ให้ยืม" }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "ยืนยัน" }));
    await waitFor(() => expect(returnToOwner).toHaveBeenCalledWith("eq-d1"));
  });

  it("is offered only to administrators, only for available demo/loan devices", async () => {
    getEquipment.mockResolvedValue(eq());
    mockUser = makeUser("equipment_pool_staff");
    const { unmount } = renderDetail();
    await screen.findByRole("heading", { name: /Demo Pump/ });
    expect(screen.queryByRole("button", { name: "คืนผู้ให้ยืม" })).not.toBeInTheDocument();
    unmount();

    mockUser = makeUser("administrator");
    getEquipment.mockResolvedValue(eq({ status: "issued_to_ward" }));
    const second = renderDetail();
    await screen.findByRole("heading", { name: /Demo Pump/ });
    expect(screen.queryByRole("button", { name: "คืนผู้ให้ยืม" })).not.toBeInTheDocument();
    second.unmount();

    getEquipment.mockResolvedValue(eq({ equipment_source: "pool", asset_number: "AST-9" }));
    renderDetail();
    await screen.findByRole("heading", { name: /Demo Pump/ });
    expect(screen.queryByRole("button", { name: "คืนผู้ให้ยืม" })).not.toBeInTheDocument();
  });

  it("a returned device shows the returned state and cannot be dispatched from here", async () => {
    getEquipment.mockResolvedValue(eq({ returned_to_owner_at: "2026-11-26T00:00:00Z" }));
    renderDetail();
    await screen.findByRole("heading", { name: /Demo Pump/ });
    expect(screen.getByText(/คืนผู้ให้ยืมแล้ว/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "คืนผู้ให้ยืม" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "เบิกเครื่องนี้" })).not.toBeInTheDocument();
  });
});

describe("monitor source badge", () => {
  it("badges demo/loan equipment in the expanded event list", async () => {
    const base: MonitorEvent = {
      id: "1",
      kind: "dispatch",
      event_at: "2026-07-28T03:00:10Z",
      business_date: "2026-07-28",
      shift: "day",
      ward: { id: "w1", name: "ICU" },
      operator: { id: "o1", full_name: "Op" },
      equipment: { id: "e1", bcm_code: "SN-100", name: "Pump", category: null, equipment_source: "loan" },
      receipt_outcome: null,
      close_reason: null,
    };
    fetchMonitorEvents.mockResolvedValue({ items: [base], next_cursor: null, total: 1 });
    wrap(<MonitorPage />);
    await userEvent.click(await screen.findByRole("button", { name: /ICU/ }));
    expect(screen.getByText("SN-100")).toBeInTheDocument();
    expect(screen.getByTestId("source-badge")).toHaveTextContent("ยืม");
  });
});

describe("admin demo/loan tab", () => {
  it("is shown to administrators and opens the batch form", async () => {
    wrap(<AdminPage />);
    await userEvent.click(screen.getByRole("button", { name: "เพิ่มเครื่อง Demo/ยืม" }));
    expect(screen.getByRole("button", { name: "ตรวจสอบ (dry run)" })).toBeInTheDocument();
  });

  it("is hidden from non-administrators", () => {
    mockUser = makeUser("equipment_pool_staff");
    wrap(<AdminPage />);
    expect(screen.queryByRole("button", { name: "เพิ่มเครื่อง Demo/ยืม" })).not.toBeInTheDocument();
  });
});
