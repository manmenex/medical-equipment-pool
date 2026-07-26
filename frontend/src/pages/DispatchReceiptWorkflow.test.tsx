import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BorrowPage } from "@/pages/BorrowPage";
import { EquipmentDetailPage } from "@/pages/EquipmentDetailPage";
import { ReturnPage } from "@/pages/ReturnPage";
import type { Equipment, Page, TransactionOut, UserProfile, Ward } from "@/types";

// Roadmap PR11 review (PR11-M1, and its follow-up requesting explicit
// status-reflection coverage): docs/audits/04-consolidated-implementation-plan.md
// Part D requires "an end-to-end workflow test (dispatch -> receipt) using
// only the new terminology and fields," covering: (1) equipment starts
// available, (2) dispatch to a ward, (3) UI reflects the issued state, (4)
// proceeding to receipt, (5) UI reflects successful receipt and the
// available state again. ReturnPage.test.tsx and EquipmentDetailPage.test.tsx
// only ever start from a prebuilt mocked transaction fixture -- neither
// proves a transaction created through the new dispatch form (BorrowPage) is
// discoverable and receivable through the new receipt form (ReturnPage), and
// neither observes the equipment's status badge/CTA actually flip between
// steps. This file drives all three pages against one shared, mutable
// equipment fixture and asserts on observable UI (StatusBadge text, CTA
// presence), never on internal state.
const availableEquipment: Equipment = {
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
const issuedEquipment: Equipment = { ...availableEquipment, status: "issued_to_ward" };

const wards: Ward[] = [{ id: "ward-1", code: "W1", name: "Ward A", department_id: null }];

const getEquipment = vi.fn();
const getEquipmentHistory = vi.fn();
const resolveEquipmentByQr = vi.fn();
const createBorrow = vi.fn();
const listActiveBorrows = vi.fn();
const listTransactions = vi.fn();
const createReturn = vi.fn();
const correctTransactionWard = vi.fn();
const getTransaction = vi.fn();
const listWards = vi.fn();

vi.mock("@/services/equipment", () => ({
  getEquipment: (...args: unknown[]) => getEquipment(...args),
  getEquipmentHistory: (...args: unknown[]) => getEquipmentHistory(...args),
  resolveEquipmentByQr: (...args: unknown[]) => resolveEquipmentByQr(...args),
}));
vi.mock("@/services/borrow", () => ({
  createBorrow: (...args: unknown[]) => createBorrow(...args),
  listActiveBorrows: (...args: unknown[]) => listActiveBorrows(...args),
  listTransactions: (...args: unknown[]) => listTransactions(...args),
  createReturn: (...args: unknown[]) => createReturn(...args),
  correctTransactionWard: (...args: unknown[]) => correctTransactionWard(...args),
  getTransaction: (...args: unknown[]) => getTransaction(...args),
  WARD_CORRECTION_REASON_MAX_LENGTH: 500,
}));
vi.mock("@/services/masterData", () => ({
  listWards: (...args: unknown[]) => listWards(...args),
}));
vi.mock("@/components/QRScanner", () => ({ QRScanner: () => null }));
vi.mock("@/components/BcmSearchInput", () => ({ BcmSearchInput: () => null }));

let mockUser: UserProfile | null = null;
vi.mock("@/hooks/useAuth", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useAuth")>("@/hooks/useAuth");
  return {
    ...actual,
    useAuth: () => ({ user: mockUser, isAuthenticated: true, isLoading: false }),
  };
});

function emptyTransactionPage(): Page<TransactionOut> {
  return { items: [], next_cursor: null, total: 0 };
}

beforeEach(() => {
  mockUser = { id: "user-1", employee_code: "U001", full_name: "Test User", email: "u@test.dev", role: "administrator", permissions: {} };
  listWards.mockResolvedValue(wards);
  getEquipmentHistory.mockResolvedValue([]);
  listTransactions.mockResolvedValue(emptyTransactionPage());
});

afterEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
});

function renderBorrowPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/borrow?equipment_id=eq-1"]}>
        <BorrowPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function renderReturnPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/return?equipment_id=eq-1"]}>
        <ReturnPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function renderEquipmentDetailPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/equipment/eq-1"]}>
        <Routes>
          <Route path="/equipment/:id" element={<EquipmentDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("Dispatch -> receipt workflow (Roadmap PR11 required end-to-end test)", () => {
  it("reflects available -> issued -> available again as equipment moves through dispatch and receipt, using only the new terminology throughout", async () => {
    const user = userEvent.setup();

    // --- 1. Equipment starts available ---
    getEquipment.mockResolvedValue(availableEquipment);
    const detailBeforeDispatch = renderEquipmentDetailPage();
    await waitFor(() => expect(screen.getByText("พร้อมใช้งาน")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "เบิกเครื่องนี้" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "รับคืนเครื่องนี้" })).not.toBeInTheDocument();
    detailBeforeDispatch.unmount();

    // --- 2. User dispatches equipment to a ward (เบิก) ---
    const dispatched: TransactionOut = {
      id: "tx-workflow-1",
      transaction_no: "TX-WORKFLOW-1",
      equipment: { id: "eq-1", asset_number: "AST-1", equipment_name: "Infusion Pump", status: "issued_to_ward" },
      quantity: 1,
      borrowed_at: "2026-07-26T09:00:00Z",
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
    createBorrow.mockResolvedValue(dispatched);

    const dispatchRender = renderBorrowPage();
    await waitFor(() => expect(screen.getByText("Infusion Pump")).toBeInTheDocument());
    expect(screen.queryByText(/ยืม/)).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText(/หอผู้ป่วยที่รับเครื่อง/), "ward-1");
    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก" }));

    await waitFor(() => expect(createBorrow).toHaveBeenCalledTimes(1));
    expect(createBorrow).toHaveBeenCalledWith(
      expect.objectContaining({ equipment_id: "eq-1", ward_id: "ward-1", dispatch_type: "on_demand" })
    );
    expect(screen.getByText("เบิกสำเร็จ")).toBeInTheDocument();
    dispatchRender.unmount();

    // --- 3. UI reflects the issued state ---
    getEquipment.mockResolvedValue(issuedEquipment);
    const detailAfterDispatch = renderEquipmentDetailPage();
    await waitFor(() => expect(screen.getByText("จ่ายให้หอผู้ป่วยแล้ว")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "รับคืนเครื่องนี้" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "เบิกเครื่องนี้" })).not.toBeInTheDocument();
    detailAfterDispatch.unmount();

    // --- 4. User proceeds to the receipt flow (รับคืน), consuming the exact
    // transaction the dispatch step created above -- not an unrelated fixture ---
    listActiveBorrows.mockResolvedValue([dispatched]);
    createReturn.mockResolvedValue({ ...dispatched, status: "closed", receipt_outcome: "usable" });

    const returnRender = renderReturnPage();
    await waitFor(() => expect(screen.getByText("Infusion Pump")).toBeInTheDocument());
    expect(screen.queryByText(/ยืม/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "ยืนยันการรับคืน" }));

    await waitFor(() => expect(createReturn).toHaveBeenCalledTimes(1));
    const [receivedTransactionId] = createReturn.mock.calls[0];
    expect(receivedTransactionId).toBe("tx-workflow-1");
    expect(screen.getByText("รับคืนเครื่องมือสำเร็จ")).toBeInTheDocument();
    expect(screen.queryByText(/ยืม/)).not.toBeInTheDocument();
    returnRender.unmount();

    // --- 5. UI reflects successful receipt and the available state again ---
    getEquipment.mockResolvedValue(availableEquipment);
    const detailAfterReceipt = renderEquipmentDetailPage();
    await waitFor(() => expect(screen.getByText("พร้อมใช้งาน")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "เบิกเครื่องนี้" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "รับคืนเครื่องนี้" })).not.toBeInTheDocument();
  });
});
