import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BorrowPage } from "@/pages/BorrowPage";
import { useUiStore } from "@/store/uiStore";
import type { Equipment, TransactionOut, Ward } from "@/types";

// Roadmap PR11 review (PR11-M1): the dispatch form had no observable
// component tests at all -- only ReturnPage.tsx's receipt side was covered.
// This file exercises BorrowPage.tsx the same way ReturnPage.test.tsx
// exercises the receipt side: the "เบิก" heading/action, the approved ward
// label + non-real-time-tracking disclaimer (Workflow Audit §7.1), the
// on-demand and routine_round payload shapes, and the absence of the
// retired "ยืม" terminology anywhere BorrowPage renders.
const equipment: Equipment = {
  id: "eq-1",
  asset_number: "AST-1",
  serial_number: null,
  equipment_name: "Infusion Pump",
  category_id: null,
  brand: null,
  model: null,
  department_owner_id: null,
  current_location_id: null,
  status: "available_at_pool",
  bcm_code: null,
  pm_due_date: null,
  cal_due_date: null,
  created_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-07-01T00:00:00Z",
};

const wards: Ward[] = [
  { id: "ward-1", code: "W1", name: "Ward A", department_id: null },
  { id: "ward-2", code: "W2", name: "Ward B", department_id: null },
];

const transaction: TransactionOut = {
  id: "tx-1",
  transaction_no: "TX-1",
  equipment: { id: "eq-1", asset_number: "AST-1", equipment_name: "Infusion Pump", status: "issued_to_ward" },
  quantity: 1,
  borrowed_at: "2026-07-21T10:00:00Z",
  returned_at: null,
  borrower_name: null,
  ward_id: "ward-1",
  dispatch_type: "on_demand",
  routine_round: null,
  phone_number: null,
  receipt_outcome: null,
  legacy_condition_on_return: null,
  status: "open",
  notes: null,
};

const getEquipment = vi.fn();
const resolveEquipmentByQr = vi.fn();
const createBorrow = vi.fn();
const listWards = vi.fn();

// Same rationale as ReturnPage.test.tsx: the QR scanner and BCM search
// inputs are unrelated dependencies (camera access, debounced network
// search) that would otherwise make this a QRScanner/BcmSearchInput test,
// not a BorrowPage dispatch-contract test. Equipment is loaded via the
// equipment_id query param, the same preset path ReturnPage.test.tsx uses.
vi.mock("@/services/equipment", () => ({
  getEquipment: (...args: unknown[]) => getEquipment(...args),
  resolveEquipmentByQr: (...args: unknown[]) => resolveEquipmentByQr(...args),
}));
vi.mock("@/services/borrow", () => ({
  createBorrow: (...args: unknown[]) => createBorrow(...args),
}));
vi.mock("@/services/masterData", () => ({
  listWards: (...args: unknown[]) => listWards(...args),
}));
vi.mock("@/components/QRScanner", () => ({ QRScanner: () => null }));
vi.mock("@/components/BcmSearchInput", () => ({ BcmSearchInput: () => null }));

beforeEach(() => {
  listWards.mockResolvedValue(wards);
  getEquipment.mockResolvedValue(equipment);
  createBorrow.mockResolvedValue(transaction);
  // Roadmap PR7b: BorrowPage seeds its ward select from the persisted
  // lastWard store on mount. Reset it per test so an earlier test's
  // successful submission never leaks a preselected ward into a later
  // test's "no selection" assertions.
  useUiStore.setState({ lastWard: null });
});

afterEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
});

function renderBorrowPage(initialEntry = "/borrow?equipment_id=eq-1") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <BorrowPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("BorrowPage scanning state (Roadmap PR11 terminology)", () => {
  it("shows the เบิก heading and never the retired ยืม terminology", () => {
    renderBorrowPage("/borrow");

    expect(screen.getByRole("heading", { name: "เบิกเครื่องมือ" })).toBeInTheDocument();
    expect(screen.queryByText(/ยืม/)).not.toBeInTheDocument();
  });
});

describe("BorrowPage dispatch form (Roadmap PR11 terminology + PR7b payload contract)", () => {
  it("shows the approved ward label and the non-real-time-tracking disclaimer (Workflow Audit §7.1)", async () => {
    renderBorrowPage();

    await waitFor(() => expect(screen.getByText("Infusion Pump")).toBeInTheDocument());

    expect(screen.getByText("หอผู้ป่วยที่รับเครื่อง (บันทึก ณ วันที่เบิก) *")).toBeInTheDocument();
    expect(
      screen.getByText("ระบบบันทึกเฉพาะหอผู้ป่วยที่ส่งเครื่องไปครั้งแรก ไม่ได้ติดตามการเคลื่อนย้ายเครื่องมือในภายหลัง")
    ).toBeInTheDocument();
  });

  it("never renders the retired ยืม terminology once equipment is loaded", async () => {
    renderBorrowPage();

    await waitFor(() => expect(screen.getByText("Infusion Pump")).toBeInTheDocument());

    expect(screen.queryByText(/ยืม/)).not.toBeInTheDocument();
  });

  it("submits an on-demand dispatch with dispatch_type 'on_demand' and no routine_round, using the เบิก confirm action", async () => {
    const user = userEvent.setup();
    renderBorrowPage();

    await waitFor(() => expect(screen.getByText("Infusion Pump")).toBeInTheDocument());

    await user.selectOptions(screen.getByLabelText(/หอผู้ป่วยที่รับเครื่อง/), "ward-1");
    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก" }));

    await waitFor(() => expect(createBorrow).toHaveBeenCalledTimes(1));
    expect(createBorrow).toHaveBeenCalledWith({
      equipment_id: "eq-1",
      ward_id: "ward-1",
      dispatch_type: "on_demand",
      routine_round: undefined,
      phone_number: undefined,
      notes: undefined,
    });
    expect(screen.getByText("เบิกสำเร็จ")).toBeInTheDocument();
  });

  it("reveals the routine-round field only for a routine_round dispatch, and includes it in the submitted payload", async () => {
    const user = userEvent.setup();
    renderBorrowPage();

    await waitFor(() => expect(screen.getByText("Infusion Pump")).toBeInTheDocument());

    expect(screen.queryByLabelText(/รอบเวลา/)).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText(/ประเภทการเบิก/), "routine_round");
    expect(screen.getByLabelText(/รอบเวลา/)).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText(/หอผู้ป่วยที่รับเครื่อง/), "ward-2");
    await user.selectOptions(screen.getByLabelText(/รอบเวลา/), "11:00");
    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก" }));

    await waitFor(() => expect(createBorrow).toHaveBeenCalledTimes(1));
    expect(createBorrow).toHaveBeenCalledWith({
      equipment_id: "eq-1",
      ward_id: "ward-2",
      dispatch_type: "routine_round",
      routine_round: "11:00",
      phone_number: undefined,
      notes: undefined,
    });
  });

  it("disables the confirm action until a routine_round dispatch also has a round selected", async () => {
    const user = userEvent.setup();
    renderBorrowPage();

    await waitFor(() => expect(screen.getByText("Infusion Pump")).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText(/หอผู้ป่วยที่รับเครื่อง/), "ward-1");
    await user.selectOptions(screen.getByLabelText(/ประเภทการเบิก/), "routine_round");

    expect(screen.getByRole("button", { name: "ยืนยันการเบิก" })).toBeDisabled();

    await user.selectOptions(screen.getByLabelText(/รอบเวลา/), "06:00");
    expect(screen.getByRole("button", { name: "ยืนยันการเบิก" })).not.toBeDisabled();
  });

  it("keeps the confirm action disabled while no ward is selected (empty/no-selection state)", async () => {
    renderBorrowPage();

    await waitFor(() => expect(screen.getByText("Infusion Pump")).toBeInTheDocument());

    expect(screen.getByLabelText(/หอผู้ป่วยที่รับเครื่อง/)).toHaveValue("");
    expect(screen.getByRole("button", { name: "ยืนยันการเบิก" })).toBeDisabled();
  });

  it("shows an error and never the success view when the dispatch API call fails", async () => {
    createBorrow.mockRejectedValue({
      isAxiosError: true,
      response: { status: 500, data: { detail: "Dispatch failed" } },
    });
    const user = userEvent.setup();
    renderBorrowPage();

    await waitFor(() => expect(screen.getByText("Infusion Pump")).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText(/หอผู้ป่วยที่รับเครื่อง/), "ward-1");
    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก" }));

    await waitFor(() => expect(screen.getByText("Dispatch failed")).toBeInTheDocument());
    expect(screen.queryByText("เบิกสำเร็จ")).not.toBeInTheDocument();
    // The form remains usable after a failed submission -- the operator is
    // not stranded on a dead page and can retry.
    expect(screen.getByRole("button", { name: "ยืนยันการเบิก" })).toBeInTheDocument();
  });
});

describe("BorrowPage equipment-loading states (Roadmap PR11 review: loading + error state coverage)", () => {
  it("shows the scanning view (no equipment card yet) while the preset equipment is still resolving", async () => {
    let resolveEquipment!: (value: Equipment) => void;
    getEquipment.mockReturnValue(new Promise<Equipment>((resolve) => (resolveEquipment = resolve)));

    renderBorrowPage();

    // Nothing about the equipment (name, ward field, confirm action) is
    // rendered yet -- only the QR/BCM scanning entry point is available
    // while the fetch is in flight.
    expect(screen.queryByText("Infusion Pump")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "ยืนยันการเบิก" })).not.toBeInTheDocument();

    resolveEquipment(equipment);
    await waitFor(() => expect(screen.getByText("Infusion Pump")).toBeInTheDocument());
  });

  it("shows an error when the preset equipment fails to resolve, and never renders the dispatch form", async () => {
    getEquipment.mockRejectedValue({ isAxiosError: true, response: { status: 404, data: {} } });

    renderBorrowPage();

    await waitFor(() => expect(screen.getByText("ไม่พบเครื่องมือ")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "ยืนยันการเบิก" })).not.toBeInTheDocument();
  });
});

// Roadmap PR11 review checklist item "permission-based disabled or hidden
// behavior": not applicable to BorrowPage itself. BorrowPage performs no
// per-role conditional rendering of its own -- access to the /borrow route
// is gated at the navigation layer (AppShell.tsx's
// canDispatchOrReceiveEquipment), which is unchanged by PR11 and outside
// this frontend-terminology PR's scope (no RBAC logic is introduced or
// modified here). Adding a role-gating test to this file would duplicate
// coverage that belongs to, and already exists for, that layer instead.
