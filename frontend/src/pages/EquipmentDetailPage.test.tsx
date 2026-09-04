import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EquipmentDetailPage } from "@/pages/EquipmentDetailPage";
import type { Equipment, EquipmentStatusHistoryItem, Page, TransactionOut, UserProfile, Ward } from "@/types";

// Roadmap PR9B review round 2 (Finding 3): the CLOSED-transaction entry
// point. GET /transactions?equipment_id=... (services/borrow.ts's
// listTransactions, already part of the merged backend contract, unchanged
// by this PR) is the actual transaction-record source -- both OPEN and
// CLOSED rows carry a real transaction ID, unlike getEquipmentHistory's
// status-history rows.

const equipment: Equipment = {
  id: "eq-1",
  asset_number: "AST-1",
  serial_number: "SN-1",
  equipment_name: "Infusion Pump",
  category_id: null,
  brand: "Acme",
  model: "X1",
  department_owner_id: null,
  current_location_id: null,
  status: "available_at_pool",
  bcm_code: "BCM-1",
  pm_due_date: null,
  cal_due_date: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const openTransaction: TransactionOut = {
  id: "tx-open-1",
  transaction_no: "TX-OPEN-1",
  equipment: { id: "eq-1", asset_number: "AST-1", equipment_name: "Infusion Pump", status: "issued_to_ward" },
  quantity: 1,
  borrowed_at: "2026-07-20T10:00:00Z",
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

const closedTransaction: TransactionOut = {
  id: "tx-closed-1",
  transaction_no: "TX-CLOSED-1",
  equipment: { id: "eq-1", asset_number: "AST-1", equipment_name: "Infusion Pump", status: "available_at_pool" },
  quantity: 1,
  borrowed_at: "2026-07-10T10:00:00Z",
  returned_at: "2026-07-12T10:00:00Z",
  borrower_name: null,
  ward_id: "ward-1",
  dispatch_type: "on_demand",
  routine_round: null,
  phone_number: null,
  receipt_outcome: "usable",
  legacy_condition_on_return: null,
  status: "closed",
  notes: null,
};

const wards: Ward[] = [
  { id: "ward-1", code: "W1", name: "Ward A", department_id: null },
  { id: "ward-2", code: "W2", name: "Ward B", department_id: null },
  { id: "ward-3", code: "W3", name: "Ward C", department_id: null },
];

const emptyHistory: EquipmentStatusHistoryItem[] = [];

const getEquipment = vi.fn();
const getEquipmentHistory = vi.fn();
const listTransactions = vi.fn();
const listWards = vi.fn();
const correctTransactionWard = vi.fn();
const getTransaction = vi.fn();

vi.mock("@/services/equipment", () => ({
  getEquipment: (...args: unknown[]) => getEquipment(...args),
  getEquipmentHistory: (...args: unknown[]) => getEquipmentHistory(...args),
}));
vi.mock("@/services/borrow", () => ({
  listTransactions: (...args: unknown[]) => listTransactions(...args),
  correctTransactionWard: (...args: unknown[]) => correctTransactionWard(...args),
  getTransaction: (...args: unknown[]) => getTransaction(...args),
  WARD_CORRECTION_REASON_MAX_LENGTH: 500,
}));
vi.mock("@/services/masterData", () => ({
  listWards: (...args: unknown[]) => listWards(...args),
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

function page(items: TransactionOut[]): Page<TransactionOut> {
  return { items, next_cursor: null, total: items.length };
}

beforeEach(() => {
  mockUser = makeUser("administrator");
  getEquipment.mockResolvedValue(equipment);
  getEquipmentHistory.mockResolvedValue(emptyHistory);
  listTransactions.mockResolvedValue(page([openTransaction, closedTransaction]));
  listWards.mockResolvedValue(wards);
});

afterEach(() => {
  vi.clearAllMocks();
});

// Roadmap PR16 Slice 4: MemoryRouter keeps its own in-memory history, not
// jsdom's real window.location -- this probe reads the router's current
// `location.search` via useLocation() (same context useSearchParams() reads
// from in EquipmentDetailPage) so tests can assert on it without depending
// on the real browser URL.
function LocationSearchProbe() {
  const location = useLocation();
  return <div data-testid="location-search">{location.search}</div>;
}

function renderPage(initialPath = "/equipment/eq-1") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <LocationSearchProbe />
        <Routes>
          <Route path="/equipment/:id" element={<EquipmentDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const TRIGGER = /แก้ไขแผนกรับเครื่อง/;
const CONFIRM_BUTTON = /ยืนยันการแก้ไข/;

async function waitForHistoryLoaded() {
  await waitFor(() => expect(screen.getByText("TX-OPEN-1", { exact: false })).toBeInTheDocument());
  await waitFor(() => expect(screen.getByText("TX-CLOSED-1", { exact: false })).toBeInTheDocument());
}

function rowFor(transactionNo: string): HTMLElement {
  return screen.getByText(transactionNo, { exact: false }).closest("li") as HTMLElement;
}

describe("EquipmentDetailPage transaction history (Roadmap PR9B review round 2, Finding 3)", () => {
  it("lists both OPEN and CLOSED transactions with their own transaction numbers", async () => {
    renderPage();
    await waitForHistoryLoaded();

    expect(screen.getByText(/อยู่ระหว่างเบิก/)).toBeInTheDocument();
    expect(screen.getByText(/รับคืนแล้ว/)).toBeInTheDocument();
  });

  it("never infers a transaction ID from the equipment ID -- the history query uses equipment_id, corrections use the real transaction id", async () => {
    renderPage();
    await waitForHistoryLoaded();

    expect(listTransactions).toHaveBeenCalledWith(expect.objectContaining({ equipment_id: "eq-1" }));
  });

  it("admin can open ward correction for an OPEN transaction", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitForHistoryLoaded();

    const openRow = rowFor("TX-OPEN-1");
    await user.click(within(openRow).getByRole("button", { name: TRIGGER }));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
  });

  it("admin can open ward correction for a CLOSED transaction", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitForHistoryLoaded();

    const closedRow = rowFor("TX-CLOSED-1");
    await user.click(within(closedRow).getByRole("button", { name: TRIGGER }));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
  });

  it("CLOSED correction submits using the exact CLOSED transaction id, never the equipment id or the OPEN transaction's id", async () => {
    correctTransactionWard.mockResolvedValue({ ...closedTransaction, ward_id: "ward-2" });
    const user = userEvent.setup();
    renderPage();
    await waitForHistoryLoaded();

    const closedRow = rowFor("TX-CLOSED-1");
    await user.click(within(closedRow).getByRole("button", { name: TRIGGER }));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText(/แผนกที่ถูกต้อง/), "ward-2");
    await user.type(screen.getByLabelText(/เหตุผลในการแก้ไข/), "Fixed after receipt");
    await user.click(screen.getByRole("button", { name: CONFIRM_BUTTON }));

    await waitFor(() => expect(correctTransactionWard).toHaveBeenCalledTimes(1));
    const [txId] = correctTransactionWard.mock.calls[0];
    expect(txId).toBe("tx-closed-1");
    expect(txId).not.toBe("eq-1");
    expect(txId).not.toBe("tx-open-1");
  });

  it("CLOSED correction is not blocked by the equipment already being available at the pool", async () => {
    // `equipment.status` is already "available_at_pool" in this fixture --
    // the correction action must not read or branch on equipment status.
    correctTransactionWard.mockResolvedValue({ ...closedTransaction, ward_id: "ward-2" });
    const user = userEvent.setup();
    renderPage();
    await waitForHistoryLoaded();

    const closedRow = rowFor("TX-CLOSED-1");
    await user.click(within(closedRow).getByRole("button", { name: TRIGGER }));
    await user.selectOptions(screen.getByLabelText(/แผนกที่ถูกต้อง/), "ward-2");
    await user.type(screen.getByLabelText(/เหตุผลในการแก้ไข/), "Fixed after receipt");
    await user.click(screen.getByRole("button", { name: CONFIRM_BUTTON }));

    await waitFor(() => expect(correctTransactionWard).toHaveBeenCalledTimes(1));
  });

  it("hides the ward-correction action from read_only for both OPEN and CLOSED transactions", async () => {
    mockUser = makeUser("read_only");
    renderPage();
    await waitForHistoryLoaded();

    expect(screen.queryAllByRole("button", { name: TRIGGER })).toHaveLength(0);
    expect(correctTransactionWard).not.toHaveBeenCalled();
  });

  it("refreshes the history after a successful CLOSED correction, without a page reload", async () => {
    correctTransactionWard.mockResolvedValue({ ...closedTransaction, ward_id: "ward-2" });
    const user = userEvent.setup();
    renderPage();
    await waitForHistoryLoaded();

    expect(listTransactions).toHaveBeenCalledTimes(1);

    listTransactions.mockResolvedValue(page([openTransaction, { ...closedTransaction, ward_id: "ward-2" }]));
    const closedRow = rowFor("TX-CLOSED-1");
    await user.click(within(closedRow).getByRole("button", { name: TRIGGER }));
    await user.selectOptions(screen.getByLabelText(/แผนกที่ถูกต้อง/), "ward-2");
    await user.type(screen.getByLabelText(/เหตุผลในการแก้ไข/), "Fixed after receipt");
    await user.click(screen.getByRole("button", { name: CONFIRM_BUTTON }));

    await waitFor(() => expect(listTransactions).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByText("แก้ไขแผนกรับเครื่องสำเร็จ")).toBeInTheDocument());
  });

  it("refreshes the history after a successful OPEN correction", async () => {
    correctTransactionWard.mockResolvedValue({ ...openTransaction, ward_id: "ward-2" });
    const user = userEvent.setup();
    renderPage();
    await waitForHistoryLoaded();

    const openRow = rowFor("TX-OPEN-1");
    await user.click(within(openRow).getByRole("button", { name: TRIGGER }));
    await user.selectOptions(screen.getByLabelText(/แผนกที่ถูกต้อง/), "ward-2");
    await user.type(screen.getByLabelText(/เหตุผลในการแก้ไข/), "Fixed a phone-in error");
    await user.click(screen.getByRole("button", { name: CONFIRM_BUTTON }));

    await waitFor(() => expect(listTransactions).toHaveBeenCalledTimes(2));
  });

  it("returns focus to the exact history-row trigger that opened the dialog after Cancel", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitForHistoryLoaded();

    const closedRow = rowFor("TX-CLOSED-1");
    const trigger = within(closedRow).getByRole("button", { name: TRIGGER });
    await user.click(trigger);
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "ยกเลิก" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });
});

// Roadmap PR9B review round 2 (Codex incremental review, PR34-R2-M2): the
// history query previously discarded next_cursor (limit:50, single page)
// and had no distinct loading/error state -- a failed fetch rendered
// identically to a genuinely empty history. These tests exercise the
// useInfiniteQuery-based fix: an explicit loading message, an explicit
// error message with a working "ลองใหม่" retry, and a "โหลดเพิ่มเติม"
// action that follows next_cursor to reach a CLOSED transaction that only
// exists on the second page.
describe("EquipmentDetailPage transaction history pagination and load state (Roadmap PR9B round 3)", () => {
  it("shows an explicit loading message while the transaction history is loading", async () => {
    listTransactions.mockReturnValue(new Promise(() => {}));
    renderPage();

    expect(await screen.findByText("กำลังโหลดประวัติการเบิก-รับคืน...")).toBeInTheDocument();
  });

  it("shows an explicit error and a retry action when the transaction history fails to load, distinct from an empty history", async () => {
    listTransactions.mockRejectedValue(new Error("network down"));
    renderPage();

    expect(await screen.findByText("ไม่สามารถโหลดประวัติการเบิก-รับคืนได้")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ลองใหม่" })).toBeInTheDocument();
    expect(screen.queryByText("ยังไม่มีประวัติการเบิก-รับคืน")).not.toBeInTheDocument();
  });

  it("retry calls the transaction-history query again and recovers on success", async () => {
    listTransactions.mockRejectedValueOnce(new Error("network down"));
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("button", { name: "ลองใหม่" });
    expect(listTransactions).toHaveBeenCalledTimes(1);

    listTransactions.mockResolvedValueOnce(page([openTransaction, closedTransaction]));
    await user.click(screen.getByRole("button", { name: "ลองใหม่" }));

    await waitFor(() => expect(screen.queryByText("ไม่สามารถโหลดประวัติการเบิก-รับคืนได้")).not.toBeInTheDocument());
    await waitForHistoryLoaded();
  });

  it('offers a "โหลดเพิ่มเติม" action only when the backend reports a next_cursor', async () => {
    listTransactions.mockResolvedValueOnce({ items: [openTransaction], next_cursor: null, total: 1 });
    renderPage();
    await waitFor(() => expect(screen.getByText("TX-OPEN-1", { exact: false })).toBeInTheDocument());

    expect(screen.queryByRole("button", { name: "โหลดเพิ่มเติม" })).not.toBeInTheDocument();
  });

  it("reaches a CLOSED transaction that only exists on a later page, using its exact transaction id", async () => {
    const laterClosedTransaction: TransactionOut = {
      ...closedTransaction,
      id: "tx-closed-page2",
      transaction_no: "TX-CLOSED-PAGE2",
    };
    listTransactions.mockImplementation(async ({ cursor }: { cursor?: string | null }) => {
      if (!cursor) {
        return { items: [openTransaction], next_cursor: "cursor-2", total: 2 };
      }
      return { items: [laterClosedTransaction], next_cursor: null, total: 2 };
    });
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => expect(screen.getByText("TX-OPEN-1", { exact: false })).toBeInTheDocument());
    expect(screen.queryByText("TX-CLOSED-PAGE2", { exact: false })).not.toBeInTheDocument();

    const loadMore = screen.getByRole("button", { name: "โหลดเพิ่มเติม" });
    await user.click(loadMore);

    await waitFor(() => expect(screen.getByText("TX-CLOSED-PAGE2", { exact: false })).toBeInTheDocument());
    expect(listTransactions).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: "cursor-2" }));

    correctTransactionWard.mockResolvedValue({ ...laterClosedTransaction, ward_id: "ward-2" });
    const laterRow = rowFor("TX-CLOSED-PAGE2");
    await user.click(within(laterRow).getByRole("button", { name: TRIGGER }));
    await user.selectOptions(screen.getByLabelText(/แผนกที่ถูกต้อง/), "ward-2");
    await user.type(screen.getByLabelText(/เหตุผลในการแก้ไข/), "Fixed on a later page");
    await user.click(screen.getByRole("button", { name: CONFIRM_BUTTON }));

    await waitFor(() => expect(correctTransactionWard).toHaveBeenCalledTimes(1));
    const [txId] = correctTransactionWard.mock.calls[0];
    expect(txId).toBe("tx-closed-page2");
  });
});

describe("EquipmentDetailPage history filters and dispatch-type/days-since display (Roadmap PR13)", () => {
  const routineTransaction: TransactionOut = {
    ...openTransaction,
    id: "tx-routine-1",
    transaction_no: "TX-ROUTINE-1",
    dispatch_type: "routine_round",
    routine_round: "11:00",
  };

  it("distinguishes an on-demand dispatch from a routine-round dispatch in the history list (Part H acceptance criterion)", async () => {
    listTransactions.mockResolvedValue(page([openTransaction, routineTransaction]));
    renderPage();
    await waitFor(() => expect(screen.getByText("TX-OPEN-1", { exact: false })).toBeInTheDocument());

    const onDemandRow = rowFor("TX-OPEN-1");
    expect(within(onDemandRow).getByText(/On-Demand/)).toBeInTheDocument();

    const routineRow = rowFor("TX-ROUTINE-1");
    expect(within(routineRow).getByText(/Routine Round/)).toBeInTheDocument();
    expect(within(routineRow).getByText(/11:00/)).toBeInTheDocument();
  });

  it('shows a "days since dispatch" indicator only for OPEN transactions', async () => {
    listTransactions.mockResolvedValue(page([openTransaction, closedTransaction]));
    renderPage();
    await waitForHistoryLoaded();

    const openRow = rowFor("TX-OPEN-1");
    expect(within(openRow).getByText(/เบิกมาแล้ว/)).toBeInTheDocument();

    const closedRow = rowFor("TX-CLOSED-1");
    expect(within(closedRow).queryByText(/เบิกมาแล้ว/)).not.toBeInTheDocument();
  });

  it("re-queries transaction history with dispatch_type when the dispatch-type filter changes", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitForHistoryLoaded();

    await user.selectOptions(screen.getByLabelText("ประเภทการเบิก"), "routine_round");

    await waitFor(() =>
      expect(listTransactions).toHaveBeenLastCalledWith(
        expect.objectContaining({ equipment_id: "eq-1", dispatch_type: "routine_round" })
      )
    );
  });

  it("re-queries transaction history with routine_round when the round filter changes, and resets it when dispatch type moves off routine_round", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitForHistoryLoaded();

    await user.selectOptions(screen.getByLabelText("ประเภทการเบิก"), "routine_round");
    await user.selectOptions(screen.getByLabelText("รอบเวลา"), "15:00");

    await waitFor(() =>
      expect(listTransactions).toHaveBeenLastCalledWith(
        expect.objectContaining({ dispatch_type: "routine_round", routine_round: "15:00" })
      )
    );

    await user.selectOptions(screen.getByLabelText("ประเภทการเบิก"), "on_demand");

    await waitFor(() =>
      expect(listTransactions).toHaveBeenLastCalledWith(
        expect.objectContaining({ dispatch_type: "on_demand", routine_round: undefined })
      )
    );
  });

  it("disables the routine-round filter unless the dispatch-type filter is set to routine_round", async () => {
    renderPage();
    await waitForHistoryLoaded();

    expect(screen.getByLabelText("รอบเวลา")).toBeDisabled();
  });

  it("re-queries transaction history with from_date/to_date when the date-range filters change", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitForHistoryLoaded();

    const fromInput = screen.getByLabelText("ตั้งแต่วันที่");
    const toInput = screen.getByLabelText("ถึงวันที่");
    await user.type(fromInput, "2026-07-01");
    await user.type(toInput, "2026-07-31");

    await waitFor(() =>
      expect(listTransactions).toHaveBeenLastCalledWith(
        expect.objectContaining({ from_date: "2026-07-01", to_date: "2026-07-31" })
      )
    );
  });
});

// ---------------------------------------------------------------------------
// Roadmap PR16 Slice 4 (docs/design/PR16_REPORTING_FOUNDATION_PLAN.md §10):
// business_date_from/business_date_to/shift/event filter controls. This
// slice is frontend only -- business_date/shift are never computed here,
// only selected and sent verbatim to GET /transactions (services/borrow.ts's
// listTransactions, unchanged contract, extended by the already-merged
// backend Slice 3). These controls are explicitly separate from the
// from_date/to_date pair covered above (Roadmap PR13): committed via
// "นำตัวกรองไปใช้" (Apply)/"ล้างตัวกรอง" (Clear), never live-onChange like
// the from_date/to_date pair, and backed by URL search params as the single
// source of truth for what was actually applied.
// ---------------------------------------------------------------------------

describe("EquipmentDetailPage business-date/shift filter controls (Roadmap PR16 Slice 4)", () => {
  it("starts with every business-date/shift control empty ('ทั้งหมด' / no date)", async () => {
    renderPage();
    await waitForHistoryLoaded();

    expect(screen.getByLabelText("วันที่ทำการ ตั้งแต่")).toHaveValue("");
    expect(screen.getByLabelText("วันที่ทำการ ถึง")).toHaveValue("");
    expect(screen.getByLabelText("กะ")).toHaveValue("");
    expect(screen.getByLabelText("เหตุการณ์")).toHaveValue("");
    // The initial, unfiltered query must not carry any of the four new
    // params at all (not even as empty strings) -- same convention as
    // dispatch_type/routine_round/from_date/to_date already established.
    expect(listTransactions).toHaveBeenCalledWith(
      expect.objectContaining({
        business_date_from: undefined,
        business_date_to: undefined,
        shift: undefined,
        event: undefined,
      })
    );
  });

  it("only sends the new filters to the API after 'นำตัวกรองไปใช้' is pressed, never on every keystroke/select", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitForHistoryLoaded();

    // event must be picked before business_date_from/business_date_to/shift
    // are enabled (PR61 review fix, H1) -- see the "date/shift controls are
    // disabled until an event is picked" tests below for that gating itself.
    await user.selectOptions(screen.getByLabelText("เหตุการณ์"), "receipt");
    await user.type(screen.getByLabelText("วันที่ทำการ ตั้งแต่"), "2026-07-01");
    await user.type(screen.getByLabelText("วันที่ทำการ ถึง"), "2026-07-31");
    await user.selectOptions(screen.getByLabelText("กะ"), "day");

    expect(listTransactions).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "นำตัวกรองไปใช้" }));

    await waitFor(() =>
      expect(listTransactions).toHaveBeenLastCalledWith(
        expect.objectContaining({
          equipment_id: "eq-1",
          business_date_from: "2026-07-01",
          business_date_to: "2026-07-31",
          shift: "day",
          event: "receipt",
        })
      )
    );
    // Never merged into, or substituted for, the existing raw-timestamp
    // from_date/to_date filter (design's explicit correction).
    expect(listTransactions).toHaveBeenLastCalledWith(
      expect.objectContaining({ from_date: undefined, to_date: undefined })
    );
  });

  it("'ล้างตัวกรอง' resets every business-date/shift/event control and re-queries without them", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitForHistoryLoaded();

    await user.selectOptions(screen.getByLabelText("เหตุการณ์"), "receipt");
    await user.type(screen.getByLabelText("วันที่ทำการ ตั้งแต่"), "2026-07-01");
    await user.selectOptions(screen.getByLabelText("กะ"), "night");
    await user.click(screen.getByRole("button", { name: "นำตัวกรองไปใช้" }));
    await waitFor(() =>
      expect(listTransactions).toHaveBeenLastCalledWith(
        expect.objectContaining({ shift: "night", event: "receipt" })
      )
    );

    await user.click(screen.getByRole("button", { name: "ล้างตัวกรอง" }));

    expect(screen.getByLabelText("วันที่ทำการ ตั้งแต่")).toHaveValue("");
    expect(screen.getByLabelText("กะ")).toHaveValue("");
    expect(screen.getByLabelText("เหตุการณ์")).toHaveValue("");
    await waitFor(() =>
      expect(listTransactions).toHaveBeenLastCalledWith(
        expect.objectContaining({
          business_date_from: undefined,
          business_date_to: undefined,
          shift: undefined,
          event: undefined,
        })
      )
    );
  });

  it("serializes applied filters into the URL query string", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitForHistoryLoaded();

    await user.selectOptions(screen.getByLabelText("เหตุการณ์"), "dispatch");
    await user.type(screen.getByLabelText("วันที่ทำการ ตั้งแต่"), "2026-07-01");
    await user.selectOptions(screen.getByLabelText("กะ"), "day");
    await user.click(screen.getByRole("button", { name: "นำตัวกรองไปใช้" }));

    await waitFor(() => {
      const search = screen.getByTestId("location-search").textContent ?? "";
      expect(search).toContain("business_date_from=2026-07-01");
      expect(search).toContain("shift=day");
      expect(search).toContain("event=dispatch");
    });
  });

  it('rejects an obviously reversed range ("ตั้งแต่" after "ถึง") client-side, without ever calling the API', async () => {
    const user = userEvent.setup();
    renderPage();
    await waitForHistoryLoaded();

    expect(listTransactions).toHaveBeenCalledTimes(1);

    await user.selectOptions(screen.getByLabelText("เหตุการณ์"), "dispatch");
    await user.type(screen.getByLabelText("วันที่ทำการ ตั้งแต่"), "2026-07-31");
    await user.type(screen.getByLabelText("วันที่ทำการ ถึง"), "2026-07-01");
    await user.click(screen.getByRole("button", { name: "นำตัวกรองไปใช้" }));

    expect(await screen.findByText(/ต้องไม่มาหลัง/)).toBeInTheDocument();
    // No second call -- the obviously-invalid range is never sent, matching
    // "frontend validation only for obvious UI mistakes."
    expect(listTransactions).toHaveBeenCalledTimes(1);
  });

  it("an equal business_date_from/business_date_to is a valid single-day range, not rejected client-side", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitForHistoryLoaded();

    await user.selectOptions(screen.getByLabelText("เหตุการณ์"), "dispatch");
    await user.type(screen.getByLabelText("วันที่ทำการ ตั้งแต่"), "2026-07-15");
    await user.type(screen.getByLabelText("วันที่ทำการ ถึง"), "2026-07-15");
    await user.click(screen.getByRole("button", { name: "นำตัวกรองไปใช้" }));

    expect(screen.queryByText(/ต้องไม่มาหลัง/)).not.toBeInTheDocument();
    await waitFor(() =>
      expect(listTransactions).toHaveBeenLastCalledWith(
        expect.objectContaining({ business_date_from: "2026-07-15", business_date_to: "2026-07-15" })
      )
    );
  });

  it("displays the backend's validation message (never a generic fallback) when GET /transactions rejects with 400 INVALID_INPUT", async () => {
    listTransactions.mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 400,
        data: { code: "INVALID_INPUT", detail: "'business_date_from' must not be after 'business_date_to'" },
      },
    });
    renderPage();

    expect(
      await screen.findByText("'business_date_from' must not be after 'business_date_to'")
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ลองใหม่" })).toBeInTheDocument();
  });

  it("shows the existing loading state while a business-date/shift-filtered query is in flight", async () => {
    listTransactions.mockReturnValue(new Promise(() => {}));
    renderPage();

    expect(await screen.findByText("กำลังโหลดประวัติการเบิก-รับคืน...")).toBeInTheDocument();
  });

  it("shows the existing empty-history state when a business-date/shift filter matches no rows", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitForHistoryLoaded();

    listTransactions.mockResolvedValue(page([]));
    await user.selectOptions(screen.getByLabelText("เหตุการณ์"), "dispatch");
    await user.type(screen.getByLabelText("วันที่ทำการ ตั้งแต่"), "2000-01-01");
    await user.type(screen.getByLabelText("วันที่ทำการ ถึง"), "2000-01-01");
    await user.click(screen.getByRole("button", { name: "นำตัวกรองไปใช้" }));

    await waitFor(() => expect(screen.getByText("ยังไม่มีประวัติการเบิก-รับคืน")).toBeInTheDocument());
  });

  it("restores applied filters from the URL on initial render, e.g. after a page refresh or shared link", async () => {
    renderPage("/equipment/eq-1?business_date_from=2026-07-01&business_date_to=2026-07-31&shift=night&event=receipt");
    await waitForHistoryLoaded();

    expect(screen.getByLabelText("วันที่ทำการ ตั้งแต่")).toHaveValue("2026-07-01");
    expect(screen.getByLabelText("วันที่ทำการ ถึง")).toHaveValue("2026-07-31");
    expect(screen.getByLabelText("กะ")).toHaveValue("night");
    expect(screen.getByLabelText("เหตุการณ์")).toHaveValue("receipt");
    expect(listTransactions).toHaveBeenCalledWith(
      expect.objectContaining({
        business_date_from: "2026-07-01",
        business_date_to: "2026-07-31",
        shift: "night",
        event: "receipt",
      })
    );
  });
});

// ---------------------------------------------------------------------------
// PR61 review fix (H1, merge-blocking): the "เหตุการณ์" select's "ทั้งหมด"
// (All) option previously serialized to `event: undefined`, and the backend
// (`Literal["dispatch", "receipt"] = "dispatch"`, backend/app/api/v1/
// transactions.py) treats an omitted `event` as "dispatch," not "all
// events" -- there is no "all" value in the API contract. So "All" silently
// behaved as "Dispatch," while the UI promised "all events." Since the
// backend cannot be changed to add an "all" value (out of scope for this
// fix) and business_date_from/business_date_to/shift are only meaningful
// together with one concrete event basis (each of dispatch/receipt has its
// own, independently derived business_date/shift -- see backend/app/crud/
// transaction.py::search()), the only way for "All" to honestly produce
// "actual all-events results" without inventing client-side dispatch/
// receipt filtering or changing backend semantics is: "All" must never be
// combined with business_date_from/business_date_to/shift on the wire, and
// those three controls are disabled until a concrete event is chosen.
// ---------------------------------------------------------------------------

describe("EquipmentDetailPage event-basis request serialization (PR61 review fix, H1)", () => {
  it("business_date_from/business_date_to/shift controls are disabled until a concrete event is chosen", async () => {
    renderPage();
    await waitForHistoryLoaded();

    expect(screen.getByLabelText("วันที่ทำการ ตั้งแต่")).toBeDisabled();
    expect(screen.getByLabelText("วันที่ทำการ ถึง")).toBeDisabled();
    expect(screen.getByLabelText("กะ")).toBeDisabled();
  });

  it("event = All (ทั้งหมด): never sends business_date_from/business_date_to/shift, producing actual all-events results", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitForHistoryLoaded();

    // Pick a concrete event first (enables the fields), fill them in, then
    // switch back to "ทั้งหมด" -- this must clear the now-meaningless
    // business_date/shift selections, not just leave `event` blank while
    // silently keeping them.
    await user.selectOptions(screen.getByLabelText("เหตุการณ์"), "dispatch");
    await user.type(screen.getByLabelText("วันที่ทำการ ตั้งแต่"), "2026-07-01");
    await user.selectOptions(screen.getByLabelText("กะ"), "day");
    await user.selectOptions(screen.getByLabelText("เหตุการณ์"), "");

    expect(screen.getByLabelText("วันที่ทำการ ตั้งแต่")).toHaveValue("");
    expect(screen.getByLabelText("กะ")).toHaveValue("");
    expect(screen.getByLabelText("วันที่ทำการ ตั้งแต่")).toBeDisabled();
    expect(screen.getByLabelText("กะ")).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "นำตัวกรองไปใช้" }));

    await waitFor(() =>
      expect(listTransactions).toHaveBeenLastCalledWith(
        expect.objectContaining({
          business_date_from: undefined,
          business_date_to: undefined,
          shift: undefined,
          event: undefined,
        })
      )
    );
  });

  it("event = Dispatch (เบิก): sends event=dispatch together with business_date_from/business_date_to/shift", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitForHistoryLoaded();

    await user.selectOptions(screen.getByLabelText("เหตุการณ์"), "dispatch");
    await user.type(screen.getByLabelText("วันที่ทำการ ตั้งแต่"), "2026-07-01");
    await user.type(screen.getByLabelText("วันที่ทำการ ถึง"), "2026-07-31");
    await user.selectOptions(screen.getByLabelText("กะ"), "day");
    await user.click(screen.getByRole("button", { name: "นำตัวกรองไปใช้" }));

    await waitFor(() =>
      expect(listTransactions).toHaveBeenLastCalledWith(
        expect.objectContaining({
          business_date_from: "2026-07-01",
          business_date_to: "2026-07-31",
          shift: "day",
          event: "dispatch",
        })
      )
    );
  });

  it("event = Receipt (รับคืน): sends event=receipt together with business_date_from/business_date_to/shift", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitForHistoryLoaded();

    await user.selectOptions(screen.getByLabelText("เหตุการณ์"), "receipt");
    await user.type(screen.getByLabelText("วันที่ทำการ ตั้งแต่"), "2026-07-01");
    await user.type(screen.getByLabelText("วันที่ทำการ ถึง"), "2026-07-31");
    await user.selectOptions(screen.getByLabelText("กะ"), "night");
    await user.click(screen.getByRole("button", { name: "นำตัวกรองไปใช้" }));

    await waitFor(() =>
      expect(listTransactions).toHaveBeenLastCalledWith(
        expect.objectContaining({
          business_date_from: "2026-07-01",
          business_date_to: "2026-07-31",
          shift: "night",
          event: "receipt",
        })
      )
    );
  });

  it("a shift/business_date_from/business_date_to already in the URL without a concrete event (e.g. a hand-edited or stale link) is never sent -- the authoritative gate is not just the Apply-time draft state", async () => {
    renderPage("/equipment/eq-1?shift=night&business_date_from=2026-07-01");
    await waitForHistoryLoaded();

    await waitFor(() =>
      expect(listTransactions).toHaveBeenCalledWith(
        expect.objectContaining({
          shift: undefined,
          business_date_from: undefined,
          business_date_to: undefined,
          event: undefined,
        })
      )
    );
  });
});
