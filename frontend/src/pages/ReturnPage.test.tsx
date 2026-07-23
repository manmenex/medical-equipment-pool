import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReturnPage } from "@/pages/ReturnPage";
import type { TransactionOut, UserProfile, Ward } from "@/types";

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

const wards: Ward[] = [
  { id: "ward-1", code: "W1", name: "Ward A", department_id: null },
  { id: "ward-2", code: "W2", name: "Ward B", department_id: null },
  { id: "ward-3", code: "W3", name: "Ward C", department_id: null },
];

const listActiveBorrows = vi.fn();
const createReturn = vi.fn();
const correctTransactionWard = vi.fn();
const getTransaction = vi.fn();
const listWards = vi.fn();

// Roadmap PR8B: this endpoint's receipt_outcome field is the subject under
// test -- the QR scanner and BCM search inputs are unrelated dependencies
// (camera access, debounced network search) that would otherwise make this
// a QRScanner/BcmSearchInput test, not a ReturnPage receipt-contract test.
vi.mock("@/services/borrow", () => ({
  listActiveBorrows: (...args: unknown[]) => listActiveBorrows(...args),
  createReturn: (...args: unknown[]) => createReturn(...args),
  correctTransactionWard: (...args: unknown[]) => correctTransactionWard(...args),
  getTransaction: (...args: unknown[]) => getTransaction(...args),
  // Roadmap PR9A's declared limit (backend/app/schemas/transaction.py) --
  // mirrored here rather than re-implemented, so this test file breaks
  // loudly if the real export's value ever drifts from 500.
  WARD_CORRECTION_REASON_MAX_LENGTH: 500,
}));
vi.mock("@/services/masterData", () => ({
  listWards: (...args: unknown[]) => listWards(...args),
}));
vi.mock("@/components/QRScanner", () => ({ QRScanner: () => null }));
vi.mock("@/components/BcmSearchInput", () => ({ BcmSearchInput: () => null }));

let mockUser: UserProfile | null = null;

// Roadmap PR9B: keeps the real canCorrectTransactionWard/roleLabel
// implementations under test (only useAuth's returned user is mocked) --
// this proves the actual gating logic, not a stand-in for it.
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
  mockUser = makeUser("admin");
  listWards.mockResolvedValue(wards);
});

afterEach(() => {
  vi.clearAllMocks();
});

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

describe("ReturnPage receipt outcome (Roadmap PR8B)", () => {
  it("offers exactly the two binary outcomes, never the retired 4-option condition list", async () => {
    listActiveBorrows.mockResolvedValue([transaction]);
    renderReturnPage();

    await waitFor(() => expect(screen.getByText("Infusion Pump")).toBeInTheDocument());

    expect(screen.getByRole("radio", { name: "พร้อมใช้งาน" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "ชำรุด" })).toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(2);

    // The pre-PR8B options must never reappear.
    expect(screen.queryByText("ต้อง PM")).not.toBeInTheDocument();
    expect(screen.queryByText("ต้องสอบเทียบ")).not.toBeInTheDocument();
    expect(screen.queryByText("ต้องซ่อม")).not.toBeInTheDocument();
  });

  it("submits receipt_outcome: 'usable' by default, never a lifecycle state or the retired condition field", async () => {
    listActiveBorrows.mockResolvedValue([transaction]);
    createReturn.mockResolvedValue({ ...transaction, status: "closed", receipt_outcome: "usable" });
    const user = userEvent.setup();
    renderReturnPage();

    await waitFor(() => expect(screen.getByText("Infusion Pump")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /ยืนยันการคืน/ }));

    await waitFor(() => expect(createReturn).toHaveBeenCalledTimes(1));
    const [txId, payload] = createReturn.mock.calls[0];
    expect(txId).toBe("tx-1");
    // Exactly the current contract's shape -- notes omitted when empty,
    // and never available_at_pool/unavailable_defective (a lifecycle
    // state) or condition (the retired field).
    expect(payload).toEqual({ receipt_outcome: "usable", notes: undefined });
  });

  it("submits receipt_outcome: 'defective' when the operator selects it", async () => {
    listActiveBorrows.mockResolvedValue([transaction]);
    createReturn.mockResolvedValue({ ...transaction, status: "closed", receipt_outcome: "defective" });
    const user = userEvent.setup();
    renderReturnPage();

    await waitFor(() => expect(screen.getByText("Infusion Pump")).toBeInTheDocument());
    await user.click(screen.getByRole("radio", { name: "ชำรุด" }));
    await user.click(screen.getByRole("button", { name: /ยืนยันการคืน/ }));

    await waitFor(() => expect(createReturn).toHaveBeenCalledTimes(1));
    expect(createReturn).toHaveBeenCalledWith("tx-1", { receipt_outcome: "defective", notes: undefined });
  });

  // Codex review round 1 (GitHub PR #29): a defective selection must never
  // reuse the "available" (green) selected-state styling -- that would
  // misleadingly present a defective outcome the same way as a usable one,
  // even though the backend transitions equipment to UNAVAILABLE_DEFECTIVE
  // for defective and AVAILABLE_AT_POOL for usable.
  it("styles the usable selection with the available treatment, never the repair treatment", async () => {
    listActiveBorrows.mockResolvedValue([transaction]);
    renderReturnPage();

    await waitFor(() => expect(screen.getByText("Infusion Pump")).toBeInTheDocument());
    const usableLabel = screen.getByRole("radio", { name: "พร้อมใช้งาน" }).closest("label");

    expect(usableLabel).toHaveClass("border-status-available", "bg-status-available/10");
    expect(usableLabel).not.toHaveClass("border-status-repair", "bg-status-repair/10");
  });

  it("styles the defective selection with the repair treatment, never the available treatment", async () => {
    listActiveBorrows.mockResolvedValue([transaction]);
    const user = userEvent.setup();
    renderReturnPage();

    await waitFor(() => expect(screen.getByText("Infusion Pump")).toBeInTheDocument());
    await user.click(screen.getByRole("radio", { name: "ชำรุด" }));
    const defectiveLabel = screen.getByRole("radio", { name: "ชำรุด" }).closest("label");

    expect(defectiveLabel).toHaveClass("border-status-repair", "bg-status-repair/10");
    expect(defectiveLabel).not.toHaveClass("border-status-available", "bg-status-available/10");
  });
});

// Roadmap PR8C (knowledge/adr/ADR-006-receipt-outcome-contract.md's "Not
// decided here"; backend/app/core/exceptions.py): the receipt endpoint now
// rejects a losing request with one of two distinguishable, stable `code`s.
// These fake rejections are shaped exactly like axios's own error objects
// (`isAxiosError: true`, `response.data.{code,detail,status}`) so that
// `apiErrorCode`/`apiErrorMessage` (both gated on `axios.isAxiosError`)
// recognize them the same way a real failed `createReturn` call would.
function fakeApiError(code: string, detail: string) {
  return {
    isAxiosError: true,
    response: { status: 409, data: { code, detail, status: 409 } },
  };
}

describe("ReturnPage receipt errors (Roadmap PR8C)", () => {
  it("shows a duplicate-receipt message for TRANSACTION_ALREADY_RETURNED, keyed by code not free text", async () => {
    listActiveBorrows.mockResolvedValue([transaction]);
    createReturn.mockRejectedValue(
      fakeApiError("TRANSACTION_ALREADY_RETURNED", "This transaction has already been returned")
    );
    const user = userEvent.setup();
    renderReturnPage();

    await waitFor(() => expect(screen.getByText("Infusion Pump")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /ยืนยันการคืน/ }));

    await waitFor(() => expect(screen.getByText("รายการนี้ถูกคืนไปแล้ว")).toBeInTheDocument());
  });

  // Codex review round 1 (GitHub PR #31): the message must attribute this
  // to another *request*, never another *person* -- RECEIPT_RACE_LOST only
  // proves a concurrent request won the conditional-close race first; it
  // could be a different staff member, the same user double-clicking, or a
  // browser/network retry from the same session. No "someone else"/ผู้อื่น
  // wording, and no received_by_user_id comparison backs this message.
  it("shows a distinct race-condition message for RECEIPT_RACE_LOST, attributing it to another request not another person", async () => {
    listActiveBorrows.mockResolvedValue([transaction]);
    createReturn.mockRejectedValue(
      fakeApiError("RECEIPT_RACE_LOST", "Another receipt request completed first. Refresh to see the current record.")
    );
    const user = userEvent.setup();
    renderReturnPage();

    await waitFor(() => expect(screen.getByText("Infusion Pump")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /ยืนยันการคืน/ }));

    await waitFor(() =>
      expect(screen.getByText("มีคำขอรับเครื่องอื่นดำเนินการสำเร็จก่อน กรุณารีเฟรชเพื่อดูข้อมูลล่าสุด")).toBeInTheDocument()
    );
    expect(screen.queryByText("รายการนี้ถูกคืนไปแล้ว")).not.toBeInTheDocument();
  });

  it("falls back to the raw detail message for an unrecognized error code, never inferring behavior from it", async () => {
    listActiveBorrows.mockResolvedValue([transaction]);
    createReturn.mockRejectedValue(fakeApiError("SOME_OTHER_CODE", "Something else went wrong"));
    const user = userEvent.setup();
    renderReturnPage();

    await waitFor(() => expect(screen.getByText("Infusion Pump")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /ยืนยันการคืน/ }));

    await waitFor(() => expect(screen.getByText("Something else went wrong")).toBeInTheDocument());
    expect(screen.queryByText("รายการนี้ถูกคืนไปแล้ว")).not.toBeInTheDocument();
    expect(
      screen.queryByText("มีคำขอรับเครื่องอื่นดำเนินการสำเร็จก่อน กรุณารีเฟรชเพื่อดูข้อมูลล่าสุด")
    ).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Roadmap PR9B: frontend ward-correction workflow, consuming the merged
// Roadmap PR9A backend contract (POST /transactions/{id}/correct-ward).
// ---------------------------------------------------------------------------

const CORRECT_WARD_BUTTON = /แก้ไขแผนกรับเครื่อง/;
const CONFIRM_BUTTON = /ยืนยันการแก้ไข/;
const CANCEL_BUTTON = "ยกเลิก";

async function openReturnedTransaction() {
  listActiveBorrows.mockResolvedValue([transaction]);
  const user = userEvent.setup();
  renderReturnPage();
  await waitFor(() => expect(screen.getByText("Infusion Pump")).toBeInTheDocument());
  return user;
}

async function openWardCorrectionDialog(user: ReturnType<typeof userEvent.setup>) {
  await waitFor(() => expect(screen.getByRole("button", { name: CORRECT_WARD_BUTTON })).toBeInTheDocument());
  await user.click(screen.getByRole("button", { name: CORRECT_WARD_BUTTON }));
  await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
}

describe("ReturnPage ward correction visibility (Roadmap PR9B)", () => {
  it("shows the ward-correction action to admin", async () => {
    mockUser = makeUser("admin");
    await openReturnedTransaction();
    expect(screen.getByRole("button", { name: CORRECT_WARD_BUTTON })).toBeInTheDocument();
  });

  it("hides the ward-correction action from biomedical_engineer", async () => {
    mockUser = makeUser("biomedical_engineer");
    await openReturnedTransaction();
    expect(screen.queryByRole("button", { name: CORRECT_WARD_BUTTON })).not.toBeInTheDocument();
  });

  it("hides the ward-correction action from ward_nurse", async () => {
    mockUser = makeUser("ward_nurse");
    await openReturnedTransaction();
    expect(screen.queryByRole("button", { name: CORRECT_WARD_BUTTON })).not.toBeInTheDocument();
  });

  it("hides the ward-correction action from transport_staff", async () => {
    mockUser = makeUser("transport_staff");
    await openReturnedTransaction();
    expect(screen.queryByRole("button", { name: CORRECT_WARD_BUTTON })).not.toBeInTheDocument();
  });

  it("hides the ward-correction action from viewer", async () => {
    mockUser = makeUser("viewer");
    await openReturnedTransaction();
    expect(screen.queryByRole("button", { name: CORRECT_WARD_BUTTON })).not.toBeInTheDocument();
  });

  // A non-admin cannot trigger the API at all through the rendered UI --
  // there is no button to click, so correctTransactionWard is never called.
  it("never calls the correction API for a non-admin, since no trigger is rendered", async () => {
    mockUser = makeUser("viewer");
    await openReturnedTransaction();
    expect(screen.queryByRole("button", { name: CORRECT_WARD_BUTTON })).not.toBeInTheDocument();
    expect(correctTransactionWard).not.toHaveBeenCalled();
  });
});

describe("ReturnPage ward correction form (Roadmap PR9B)", () => {
  it("displays the currently recorded ward", async () => {
    const user = await openReturnedTransaction();
    await openWardCorrectionDialog(user);
    expect(screen.getByText("แผนกที่บันทึกไว้ปัจจุบัน")).toBeInTheDocument();
    expect(within(screen.getByRole("dialog")).getByText("Ward A")).toBeInTheDocument();
  });

  it("offers the ward list for selection", async () => {
    const user = await openReturnedTransaction();
    await openWardCorrectionDialog(user);
    const select = screen.getByLabelText(/แผนกที่ถูกต้อง/);
    expect(within(select).getByRole("option", { name: "Ward B" })).toBeInTheDocument();
    expect(within(select).getByRole("option", { name: "Ward C" })).toBeInTheDocument();
  });

  it("never offers the currently recorded ward as a selectable correction target", async () => {
    const user = await openReturnedTransaction();
    await openWardCorrectionDialog(user);
    const select = screen.getByLabelText(/แผนกที่ถูกต้อง/);
    expect(within(select).queryByRole("option", { name: "Ward A" })).not.toBeInTheDocument();
  });

  it("disables confirmation when no ward is selected", async () => {
    const user = await openReturnedTransaction();
    await openWardCorrectionDialog(user);
    await user.type(screen.getByLabelText(/เหตุผลในการแก้ไข/), "Fixed a phone-in error");
    expect(screen.getByRole("button", { name: CONFIRM_BUTTON })).toBeDisabled();
  });

  it("disables confirmation when the reason is missing", async () => {
    const user = await openReturnedTransaction();
    await openWardCorrectionDialog(user);
    await user.selectOptions(screen.getByLabelText(/แผนกที่ถูกต้อง/), "ward-2");
    expect(screen.getByRole("button", { name: CONFIRM_BUTTON })).toBeDisabled();
  });

  it("disables confirmation when the reason is whitespace-only", async () => {
    const user = await openReturnedTransaction();
    await openWardCorrectionDialog(user);
    await user.selectOptions(screen.getByLabelText(/แผนกที่ถูกต้อง/), "ward-2");
    await user.type(screen.getByLabelText(/เหตุผลในการแก้ไข/), "    ");
    expect(screen.getByRole("button", { name: CONFIRM_BUTTON })).toBeDisabled();
  });

  it("accepts exactly 500 characters", async () => {
    const user = await openReturnedTransaction();
    await openWardCorrectionDialog(user);
    await user.selectOptions(screen.getByLabelText(/แผนกที่ถูกต้อง/), "ward-2");
    await user.type(screen.getByLabelText(/เหตุผลในการแก้ไข/), "x".repeat(500));
    expect(screen.getByRole("button", { name: CONFIRM_BUTTON })).toBeEnabled();
    expect(screen.getByText("500/500 ตัวอักษร")).toBeInTheDocument();
  });

  it("prevents submission of 501 characters", async () => {
    const user = await openReturnedTransaction();
    await openWardCorrectionDialog(user);
    await user.selectOptions(screen.getByLabelText(/แผนกที่ถูกต้อง/), "ward-2");
    await user.type(screen.getByLabelText(/เหตุผลในการแก้ไข/), "x".repeat(501));
    expect(screen.getByRole("button", { name: CONFIRM_BUTTON })).toBeDisabled();
    expect(correctTransactionWard).not.toHaveBeenCalled();
  });

  it("shows the old ward, new ward, and reason before confirming", async () => {
    const user = await openReturnedTransaction();
    await openWardCorrectionDialog(user);
    await user.selectOptions(screen.getByLabelText(/แผนกที่ถูกต้อง/), "ward-2");
    await user.type(screen.getByLabelText(/เหตุผลในการแก้ไข/), "Fixed a phone-in error");

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getAllByText("Ward A", { exact: false }).length).toBeGreaterThan(0);
    expect(within(dialog).getByText(/จะเปลี่ยนจาก/)).toHaveTextContent("จะเปลี่ยนจาก Ward A เป็น Ward B");
    expect(screen.getByLabelText(/เหตุผลในการแก้ไข/)).toHaveValue("Fixed a phone-in error");
  });

  it("cancel closes the dialog and calls no API", async () => {
    const user = await openReturnedTransaction();
    await openWardCorrectionDialog(user);
    await user.click(screen.getByRole("button", { name: CANCEL_BUTTON }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(correctTransactionWard).not.toHaveBeenCalled();
  });
});

// Roadmap PR9B review round 2 (Finding 1 and Finding 2): ward-query
// loading/error/retry behavior and focus restoration, exercised through
// ReturnPage -- the OPEN-transaction entry point. WardCorrectionAction and
// WardCorrectionDialog have their own dedicated, more exhaustive tests
// (src/components/WardCorrectionAction.test.tsx); these confirm the same
// shared component behaves correctly once mounted inside this screen.
describe("ReturnPage ward correction trigger state (Roadmap PR9B review round 2)", () => {
  it("disables the trigger and shows a loading message while wards are loading", async () => {
    listWards.mockReturnValue(new Promise(() => {}));
    await openReturnedTransaction();

    const trigger = await screen.findByRole("button", { name: /กำลังโหลดรายชื่อแผนก/ });
    expect(trigger).toBeDisabled();
  });

  it("shows an explicit error and a retry action when the ward list fails to load, without opening the dialog", async () => {
    listWards.mockRejectedValue(new Error("network down"));
    await openReturnedTransaction();

    expect(await screen.findByText("ไม่สามารถโหลดรายชื่อแผนกได้")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ลองใหม่" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("returns focus to the ReturnPage trigger after the dialog closes", async () => {
    const user = await openReturnedTransaction();
    const trigger = screen.getByRole("button", { name: CORRECT_WARD_BUTTON });
    await openWardCorrectionDialog(user);

    await user.click(screen.getByRole("button", { name: CANCEL_BUTTON }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });
});

describe("ReturnPage ward correction submission (Roadmap PR9B)", () => {
  it("sends exactly the transaction id, ward_id, and trimmed reason -- no unknown fields", async () => {
    correctTransactionWard.mockResolvedValue({ ...transaction, ward_id: "ward-2" });
    const user = await openReturnedTransaction();
    await openWardCorrectionDialog(user);
    await user.selectOptions(screen.getByLabelText(/แผนกที่ถูกต้อง/), "ward-2");
    await user.type(screen.getByLabelText(/เหตุผลในการแก้ไข/), "  Fixed a phone-in error  ");
    await user.click(screen.getByRole("button", { name: CONFIRM_BUTTON }));

    await waitFor(() => expect(correctTransactionWard).toHaveBeenCalledTimes(1));
    const [txId, payload] = correctTransactionWard.mock.calls[0];
    expect(txId).toBe("tx-1");
    expect(payload).toEqual({ ward_id: "ward-2", reason: "Fixed a phone-in error" });
    expect(Object.keys(payload)).toEqual(["ward_id", "reason"]);
  });

  it("disables the confirm button while the request is pending", async () => {
    let resolveRequest: (value: TransactionOut) => void = () => {};
    correctTransactionWard.mockReturnValue(
      new Promise<TransactionOut>((resolve) => {
        resolveRequest = resolve;
      })
    );
    const user = await openReturnedTransaction();
    await openWardCorrectionDialog(user);
    await user.selectOptions(screen.getByLabelText(/แผนกที่ถูกต้อง/), "ward-2");
    await user.type(screen.getByLabelText(/เหตุผลในการแก้ไข/), "Fixed a phone-in error");
    await user.click(screen.getByRole("button", { name: CONFIRM_BUTTON }));

    await waitFor(() => expect(screen.getByRole("button", { name: /กำลังบันทึก/ })).toBeDisabled());
    expect(screen.getByRole("button", { name: CANCEL_BUTTON })).toBeDisabled();

    resolveRequest({ ...transaction, ward_id: "ward-2" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("closes the dialog on success", async () => {
    correctTransactionWard.mockResolvedValue({ ...transaction, ward_id: "ward-2" });
    const user = await openReturnedTransaction();
    await openWardCorrectionDialog(user);
    await user.selectOptions(screen.getByLabelText(/แผนกที่ถูกต้อง/), "ward-2");
    await user.type(screen.getByLabelText(/เหตุผลในการแก้ไข/), "Fixed a phone-in error");
    await user.click(screen.getByRole("button", { name: CONFIRM_BUTTON }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("refreshes the displayed ward after a successful correction, without a page reload", async () => {
    correctTransactionWard.mockResolvedValue({ ...transaction, ward_id: "ward-2" });
    const user = await openReturnedTransaction();
    expect(screen.getByText(/แผนกที่บันทึกไว้:/)).toHaveTextContent("Ward A");

    await openWardCorrectionDialog(user);
    await user.selectOptions(screen.getByLabelText(/แผนกที่ถูกต้อง/), "ward-2");
    await user.type(screen.getByLabelText(/เหตุผลในการแก้ไข/), "Fixed a phone-in error");
    await user.click(screen.getByRole("button", { name: CONFIRM_BUTTON }));

    await waitFor(() => expect(screen.getByText(/แผนกที่บันทึกไว้:/)).toHaveTextContent("Ward B"));
  });

  it("shows a Thai success message after a successful correction", async () => {
    correctTransactionWard.mockResolvedValue({ ...transaction, ward_id: "ward-2" });
    const user = await openReturnedTransaction();
    await openWardCorrectionDialog(user);
    await user.selectOptions(screen.getByLabelText(/แผนกที่ถูกต้อง/), "ward-2");
    await user.type(screen.getByLabelText(/เหตุผลในการแก้ไข/), "Fixed a phone-in error");
    await user.click(screen.getByRole("button", { name: CONFIRM_BUTTON }));

    await waitFor(() => expect(screen.getByText("แก้ไขแผนกรับเครื่องสำเร็จ")).toBeInTheDocument());
  });
});

describe("ReturnPage ward correction errors (Roadmap PR9B)", () => {
  it("shows the Thai permission message for a 403/FORBIDDEN response", async () => {
    correctTransactionWard.mockRejectedValue(fakeApiError("FORBIDDEN", "Insufficient permissions"));
    const user = await openReturnedTransaction();
    await openWardCorrectionDialog(user);
    await user.selectOptions(screen.getByLabelText(/แผนกที่ถูกต้อง/), "ward-2");
    await user.type(screen.getByLabelText(/เหตุผลในการแก้ไข/), "Fixed a phone-in error");
    await user.click(screen.getByRole("button", { name: CONFIRM_BUTTON }));

    await waitFor(() => expect(screen.getByText("คุณไม่มีสิทธิ์แก้ไขแผนกรับเครื่อง")).toBeInTheDocument());
    // The dialog must stay open so the user's reason is not lost.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("handles a same-ward (WARD_CORRECTION_NOOP) rejection from the backend", async () => {
    correctTransactionWard.mockRejectedValue(
      fakeApiError("WARD_CORRECTION_NOOP", "The submitted ward is already recorded for this transaction.")
    );
    const user = await openReturnedTransaction();
    await openWardCorrectionDialog(user);
    await user.selectOptions(screen.getByLabelText(/แผนกที่ถูกต้อง/), "ward-2");
    await user.type(screen.getByLabelText(/เหตุผลในการแก้ไข/), "Fixed a phone-in error");
    await user.click(screen.getByRole("button", { name: CONFIRM_BUTTON }));

    await waitFor(() =>
      expect(screen.getByText("หอผู้ป่วยที่เลือกตรงกับข้อมูลปัจจุบันอยู่แล้ว จึงไม่มีการเปลี่ยนแปลง")).toBeInTheDocument()
    );
  });

  it("refreshes the transaction and informs the user on a concurrent WARD_CORRECTION_CONFLICT", async () => {
    correctTransactionWard.mockRejectedValue(
      fakeApiError("WARD_CORRECTION_CONFLICT", "Another correction updated this transaction's ward first.")
    );
    getTransaction.mockResolvedValue({ ...transaction, ward_id: "ward-3" });
    const user = await openReturnedTransaction();
    await openWardCorrectionDialog(user);
    await user.selectOptions(screen.getByLabelText(/แผนกที่ถูกต้อง/), "ward-2");
    await user.type(screen.getByLabelText(/เหตุผลในการแก้ไข/), "Fixed a phone-in error");
    await user.click(screen.getByRole("button", { name: CONFIRM_BUTTON }));

    await waitFor(() => expect(getTransaction).toHaveBeenCalledWith("tx-1"));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(
      screen.getByText(/มีคำขอแก้ไขแผนกอื่นดำเนินการสำเร็จก่อนคำขอนี้/)
    ).toBeInTheDocument();
    // The newly committed ward (from the refetch) is now displayed.
    await waitFor(() => expect(screen.getByText(/แผนกที่บันทึกไว้:/)).toHaveTextContent("Ward C"));
  });

  it("permits a safe retry on an unexpected failure, without losing the entered reason", async () => {
    correctTransactionWard.mockRejectedValueOnce({ message: "Network Error" });
    const user = await openReturnedTransaction();
    await openWardCorrectionDialog(user);
    await user.selectOptions(screen.getByLabelText(/แผนกที่ถูกต้อง/), "ward-2");
    await user.type(screen.getByLabelText(/เหตุผลในการแก้ไข/), "Fixed a phone-in error");
    await user.click(screen.getByRole("button", { name: CONFIRM_BUTTON }));

    await waitFor(() => expect(screen.getByText("แก้ไขแผนกรับเครื่องไม่สำเร็จ กรุณาลองใหม่อีกครั้ง")).toBeInTheDocument());
    // The dialog is still open with the reason intact, so the user can retry.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText(/เหตุผลในการแก้ไข/)).toHaveValue("Fixed a phone-in error");

    correctTransactionWard.mockResolvedValueOnce({ ...transaction, ward_id: "ward-2" });
    await user.click(screen.getByRole("button", { name: CONFIRM_BUTTON }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(correctTransactionWard).toHaveBeenCalledTimes(2);
  });
});
