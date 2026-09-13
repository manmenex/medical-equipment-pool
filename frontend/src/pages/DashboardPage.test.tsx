import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardPage } from "@/pages/DashboardPage";
import type { DashboardSummary, UserProfile } from "@/types";

// Dashboard & Equipment Status (unnumbered Post-PR11 frontend follow-up):
// observable-behavior coverage
// for the redesigned dashboard -- the four confirmed lifecycle-status
// counts, loading/empty/error states, quick-action destinations, and
// permission-gated dispatch/receipt quick actions (mirroring AppShell.tsx's
// own canDispatchOrReceiveEquipment gate).
const summary: DashboardSummary = {
  total: 42,
  available_at_pool: 20,
  issued_to_ward: 15,
  unavailable_defective: 5,
  decommissioned: 2,
};

const emptySummary: DashboardSummary = {
  total: 0,
  available_at_pool: 0,
  issued_to_ward: 0,
  unavailable_defective: 0,
  decommissioned: 0,
};

const fetchSummary = vi.fn();

vi.mock("@/services/dashboard", () => ({
  fetchSummary: (...args: unknown[]) => fetchSummary(...args),
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

beforeEach(() => {
  mockUser = makeUser("administrator");
});

afterEach(() => {
  vi.clearAllMocks();
});

function renderDashboard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/"]}>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("DashboardPage rendering and lifecycle-status counts", () => {
  it("renders the page title and all four confirmed lifecycle-status counts, plus the running total", async () => {
    fetchSummary.mockResolvedValue(summary);
    renderDashboard();

    expect(screen.getByRole("heading", { name: "ภาพรวมระบบ" })).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText("42")).toBeInTheDocument());
    expect(screen.getByText("20")).toBeInTheDocument();
    expect(screen.getByText("15")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();

    expect(screen.getByText("พร้อมใช้งาน")).toBeInTheDocument();
    expect(screen.getByText("จ่ายให้หอผู้ป่วยแล้ว")).toBeInTheDocument();
    expect(screen.getByText("ไม่พร้อมใช้งาน")).toBeInTheDocument();
    expect(screen.getByText("ปลดระวางถาวร")).toBeInTheDocument();
  });

  it("links each status count to the equipment list filtered by that exact status", async () => {
    fetchSummary.mockResolvedValue(summary);
    renderDashboard();

    await waitFor(() => expect(screen.getByText("20")).toBeInTheDocument());

    expect(screen.getByText("พร้อมใช้งาน").closest("a")).toHaveAttribute(
      "href",
      "/equipment?status=available_at_pool"
    );
    expect(screen.getByText("จ่ายให้หอผู้ป่วยแล้ว").closest("a")).toHaveAttribute(
      "href",
      "/equipment?status=issued_to_ward"
    );
    expect(screen.getByText("ไม่พร้อมใช้งาน").closest("a")).toHaveAttribute(
      "href",
      "/equipment?status=unavailable_defective"
    );
    expect(screen.getByText("ปลดระวางถาวร").closest("a")).toHaveAttribute("href", "/equipment?status=decommissioned");
  });

  it("shows no chart or analytics content beyond the simple operational counts", async () => {
    fetchSummary.mockResolvedValue(summary);
    renderDashboard();

    await waitFor(() => expect(screen.getByText("42")).toBeInTheDocument());

    expect(document.querySelector(".recharts-wrapper")).not.toBeInTheDocument();
  });

  // Review PR40-H2 / Roadmap PR13: docs/audits/04-consolidated-implementation-plan.md's
  // PR13 entry retires PM/Calibration widgets as "MVP-irrelevant
  // dashboard/report elements" -- the backend summary (Roadmap PR13) no
  // longer even returns pm_due_soon/cal_due_soon, and this dashboard must
  // never reintroduce them.
  it("never renders PM or Calibration due-soon widgets", async () => {
    fetchSummary.mockResolvedValue(summary);
    renderDashboard();

    await waitFor(() => expect(screen.getByText("42")).toBeInTheDocument());

    expect(screen.queryByText(/PM ใกล้ครบกำหนด/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Calibration ใกล้ครบกำหนด/)).not.toBeInTheDocument();
  });
});

describe("DashboardPage loading, empty, and error states", () => {
  it("shows a loading state while the summary is in flight, before any counts render", async () => {
    let resolveSummary!: (value: DashboardSummary) => void;
    fetchSummary.mockReturnValue(new Promise<DashboardSummary>((resolve) => (resolveSummary = resolve)));

    renderDashboard();

    expect(screen.getByText("กำลังโหลด...")).toBeInTheDocument();
    expect(screen.queryByText("พร้อมใช้งาน")).not.toBeInTheDocument();

    resolveSummary(summary);
    await waitFor(() => expect(screen.getByText("พร้อมใช้งาน")).toBeInTheDocument());
  });

  it("shows an empty state when the pool has zero equipment, instead of a zeroed-out count grid", async () => {
    fetchSummary.mockResolvedValue(emptySummary);
    renderDashboard();

    await waitFor(() => expect(screen.getByText("ยังไม่มีข้อมูลเครื่องมือในระบบ")).toBeInTheDocument());
    expect(screen.queryByText("พร้อมใช้งาน")).not.toBeInTheDocument();
  });

  it("shows an error state with a working retry action when the summary fails to load", async () => {
    fetchSummary.mockRejectedValue(new Error("network down"));
    const user = userEvent.setup();
    renderDashboard();

    await waitFor(() => expect(screen.getByText("ไม่สามารถโหลดข้อมูลภาพรวมได้")).toBeInTheDocument());
    expect(screen.queryByText("พร้อมใช้งาน")).not.toBeInTheDocument();

    fetchSummary.mockResolvedValueOnce(summary);
    await user.click(screen.getByRole("button", { name: "ลองใหม่" }));

    await waitFor(() => expect(screen.getByText("พร้อมใช้งาน")).toBeInTheDocument());
    expect(fetchSummary).toHaveBeenCalledTimes(2);
  });
});

describe("DashboardPage quick actions", () => {
  it("renders the scan, equipment-list, and report quick actions with their target routes", async () => {
    fetchSummary.mockResolvedValue(summary);
    renderDashboard();

    await waitFor(() => expect(screen.getByText("พร้อมใช้งาน")).toBeInTheDocument());

    expect(screen.getByRole("link", { name: /สแกน QR/ })).toHaveAttribute("href", "/scan");
    expect(screen.getByRole("link", { name: /ดูรายการเครื่อง/ })).toHaveAttribute("href", "/equipment");
    expect(screen.getByRole("link", { name: /ดูรายงาน/ })).toHaveAttribute("href", "/reports");
  });

  // Review PR40-M1: the label must describe what /reports
  // actually shows (a dispatch-frequency chart plus export controls, per
  // ReportsPage.tsx) rather than promising a transaction-history list that
  // does not exist -- "ดูประวัติรายการ" would have been that false promise.
  it("labels the /reports quick action to match what that page actually shows, never as unbuilt transaction history", async () => {
    fetchSummary.mockResolvedValue(summary);
    renderDashboard();

    await waitFor(() => expect(screen.getByText("พร้อมใช้งาน")).toBeInTheDocument());

    expect(screen.queryByText("ดูประวัติรายการ")).not.toBeInTheDocument();
    expect(screen.getByText("ดูรายงาน")).toBeInTheDocument();
  });

  it("shows the dispatch and receive quick actions for a role that can perform them", async () => {
    mockUser = makeUser("equipment_pool_staff");
    fetchSummary.mockResolvedValue(summary);
    renderDashboard();

    await waitFor(() => expect(screen.getByText("พร้อมใช้งาน")).toBeInTheDocument());

    expect(screen.getByRole("link", { name: /จ่ายเครื่อง/ })).toHaveAttribute("href", "/borrow");
    expect(screen.getByRole("link", { name: /รับเครื่อง/ })).toHaveAttribute("href", "/return");
  });

  it("hides the dispatch and receive quick actions for read_only", async () => {
    mockUser = makeUser("read_only");
    fetchSummary.mockResolvedValue(summary);
    renderDashboard();

    await waitFor(() => expect(screen.getByText("พร้อมใช้งาน")).toBeInTheDocument());

    expect(screen.queryByRole("link", { name: /จ่ายเครื่อง/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /รับเครื่อง/ })).not.toBeInTheDocument();
    // Quick actions available to every role remain visible regardless.
    expect(screen.getByRole("link", { name: /สแกน QR/ })).toBeInTheDocument();
  });

  it("still shows the always-available quick actions while the summary is loading", () => {
    fetchSummary.mockReturnValue(new Promise(() => {}));
    renderDashboard();

    expect(screen.getByRole("link", { name: /สแกน QR/ })).toHaveAttribute("href", "/scan");
    expect(screen.getByRole("link", { name: /ดูรายการเครื่อง/ })).toHaveAttribute("href", "/equipment");
  });
});
