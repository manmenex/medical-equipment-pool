import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BorrowPage } from "@/pages/BorrowPage";
import { EquipmentDetailPage } from "@/pages/EquipmentDetailPage";
import { ReturnPage } from "@/pages/ReturnPage";
import type { BorrowPayload, ReturnPayload } from "@/services/borrow";
import type { Equipment, Page, TransactionOut, UserProfile, Ward } from "@/types";

// Roadmap PR11 review (PR11-M1, and its follow-up PR11-M1R): docs/audits/
// 04-consolidated-implementation-plan.md Part D requires "an end-to-end
// workflow test (dispatch -> receipt) using only the new terminology and
// fields," covering: (1) equipment starts available, (2) dispatch to a
// ward, (3) UI reflects the issued state, (4) proceeding to receipt, (5) UI
// reflects successful receipt and the available state again.
//
// PR11-M1R specifically: an earlier version of this file manually swapped
// `getEquipment`'s mocked resolved value between steps (available ->
// issued -> available) instead of deriving that state from the dispatch and
// receipt actions themselves -- so the test would still pass even if
// createBorrow/createReturn never actually changed anything. This version
// backs the mocked service layer with one shared, mutable in-memory store:
// createBorrow is the only thing that flips the store's equipment to
// issued_to_ward and creates the transaction; createReturn is the only
// thing that closes that exact transaction id and flips the store back to
// available_at_pool; every getEquipment/listActiveBorrows/listTransactions
// response is derived by reading the store, never hand-fed per step. If
// either action stops actually mutating the store, the later UI assertions
// fail.
const EQUIPMENT_ID = "eq-1";

function makeAvailableEquipment(): Equipment {
  return {
    id: EQUIPMENT_ID,
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
}

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

// --- The shared, mutable backing store the mocked service layer reads
// from and writes to. This is the only source of truth for equipment
// status and transaction state across every render in the test below. ---
let store: { equipment: Equipment; transactions: TransactionOut[] };
let nextTransactionId: number;

beforeEach(() => {
  mockUser = { id: "user-1", employee_code: "U001", full_name: "Test User", email: "u@test.dev", role: "administrator", permissions: {} };
  store = { equipment: makeAvailableEquipment(), transactions: [] };
  nextTransactionId = 1;

  listWards.mockResolvedValue(wards);
  getEquipmentHistory.mockResolvedValue([]);

  getEquipment.mockImplementation(async (id: string) => {
    if (id !== store.equipment.id) throw new Error(`unexpected equipment id: ${id}`);
    return { ...store.equipment };
  });

  // The only place equipment moves to issued_to_ward and a transaction is
  // created -- exactly what a real POST /borrow does server-side.
  createBorrow.mockImplementation(async (payload: BorrowPayload) => {
    const tx: TransactionOut = {
      id: `tx-workflow-${nextTransactionId++}`,
      transaction_no: "TX-WORKFLOW-1",
      equipment: {
        id: store.equipment.id,
        asset_number: store.equipment.asset_number,
        equipment_name: store.equipment.equipment_name,
        status: "issued_to_ward",
      },
      quantity: 1,
      borrowed_at: "2026-07-26T09:00:00Z",
      returned_at: null,
      borrower_name: null,
      ward_id: payload.ward_id,
      dispatch_type: payload.dispatch_type,
      routine_round: payload.routine_round ?? null,
      phone_number: payload.phone_number ?? null,
      receipt_outcome: null,
      legacy_condition_on_return: null,
      status: "open",
      notes: payload.notes ?? null,
    };
    store.equipment = { ...store.equipment, status: "issued_to_ward" };
    store.transactions = [...store.transactions, tx];
    return tx;
  });

  listActiveBorrows.mockImplementation(async () => store.transactions.filter((tx) => tx.status === "open"));

  listTransactions.mockImplementation(async (params: { equipment_id?: string }): Promise<Page<TransactionOut>> => {
    const items = store.transactions.filter((tx) => !params.equipment_id || tx.equipment.id === params.equipment_id);
    return { items, next_cursor: null, total: items.length };
  });

  // The only place a transaction closes and equipment moves back to
  // available_at_pool -- exactly what a real POST /return/{id} does
  // server-side. Rejects if the id doesn't match a real open transaction,
  // the same way the backend would.
  createReturn.mockImplementation(async (transactionId: string, payload: ReturnPayload) => {
    const existing = store.transactions.find((tx) => tx.id === transactionId);
    if (!existing) throw new Error(`no such open transaction: ${transactionId}`);
    const closed: TransactionOut = {
      ...existing,
      status: "closed",
      returned_at: "2026-07-26T10:00:00Z",
      receipt_outcome: payload.receipt_outcome,
    };
    store.transactions = store.transactions.map((tx) => (tx.id === transactionId ? closed : tx));
    store.equipment = { ...store.equipment, status: "available_at_pool" };
    return closed;
  });
});

afterEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
});

function renderBorrowPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/borrow?equipment_id=${EQUIPMENT_ID}`]}>
        <BorrowPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function renderReturnPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/return?equipment_id=${EQUIPMENT_ID}`]}>
        <ReturnPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function renderEquipmentDetailPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/equipment/${EQUIPMENT_ID}`]}>
        <Routes>
          <Route path="/equipment/:id" element={<EquipmentDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("Dispatch -> receipt workflow (Roadmap PR11 required end-to-end test, stateful per PR11-M1R)", () => {
  it("reflects available -> issued -> available again, where each transition is driven by the dispatch/receipt action itself, not by the test", async () => {
    const user = userEvent.setup();

    // --- 1. Equipment starts available ---
    const detailBeforeDispatch = renderEquipmentDetailPage();
    await waitFor(() => expect(screen.getByText("พร้อมใช้งาน")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "เบิกเครื่องนี้" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "รับคืนเครื่องนี้" })).not.toBeInTheDocument();
    detailBeforeDispatch.unmount();

    expect(store.equipment.status).toBe("available_at_pool");
    expect(store.transactions).toHaveLength(0);

    // --- 2. User dispatches equipment to a ward (เบิก) ---
    const dispatchRender = renderBorrowPage();
    await waitFor(() => expect(screen.getByText("Infusion Pump")).toBeInTheDocument());
    expect(screen.queryByText(/ยืม/)).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText(/หอผู้ป่วยที่รับเครื่อง/), "ward-1");
    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก" }));

    await waitFor(() => expect(createBorrow).toHaveBeenCalledTimes(1));
    expect(createBorrow).toHaveBeenCalledWith(
      expect.objectContaining({ equipment_id: EQUIPMENT_ID, ward_id: "ward-1", dispatch_type: "on_demand" })
    );
    expect(screen.getByText("เบิกสำเร็จ")).toBeInTheDocument();
    dispatchRender.unmount();

    // The dispatch action itself must have advanced the shared store --
    // nothing in this test sets these directly.
    expect(store.equipment.status).toBe("issued_to_ward");
    expect(store.transactions).toHaveLength(1);
    const createdTransactionId = store.transactions[0].id;

    // --- 3. UI reflects the issued state, read from the store createBorrow mutated ---
    const detailAfterDispatch = renderEquipmentDetailPage();
    await waitFor(() => expect(screen.getByText("จ่ายให้หอผู้ป่วยแล้ว")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "รับคืนเครื่องนี้" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "เบิกเครื่องนี้" })).not.toBeInTheDocument();
    detailAfterDispatch.unmount();

    // --- 4. User proceeds to the receipt flow (รับคืน). ReturnPage discovers
    // the transaction via listActiveBorrows, which is itself derived from
    // the store -- not fed the dispatch step's transaction object directly. ---
    const returnRender = renderReturnPage();
    await waitFor(() => expect(screen.getByText("Infusion Pump")).toBeInTheDocument());
    expect(screen.queryByText(/ยืม/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "ยืนยันการรับคืน" }));

    await waitFor(() => expect(createReturn).toHaveBeenCalledTimes(1));
    const [receivedTransactionId] = createReturn.mock.calls[0];
    // Proves the receipt step closed the exact transaction the dispatch
    // step created, not an unrelated fixture or a different id.
    expect(receivedTransactionId).toBe(createdTransactionId);
    expect(screen.getByText("รับคืนเครื่องมือสำเร็จ")).toBeInTheDocument();
    expect(screen.queryByText(/ยืม/)).not.toBeInTheDocument();
    returnRender.unmount();

    // The receipt action itself must have closed the transaction and
    // restored the store's equipment status -- nothing in this test sets
    // these directly.
    expect(store.equipment.status).toBe("available_at_pool");
    expect(store.transactions[0].status).toBe("closed");

    // --- 5. UI reflects successful receipt and the available state again,
    // read from the store createReturn mutated ---
    const detailAfterReceipt = renderEquipmentDetailPage();
    await waitFor(() => expect(screen.getByText("พร้อมใช้งาน")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "เบิกเครื่องนี้" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "รับคืนเครื่องนี้" })).not.toBeInTheDocument();
  });

  it("rejects a receipt attempt against a transaction id the dispatch step never created (sanity check on the stateful mock itself)", async () => {
    await expect(createReturn("tx-does-not-exist", { receipt_outcome: "usable" })).rejects.toThrow(
      /no such open transaction/
    );
  });
});
