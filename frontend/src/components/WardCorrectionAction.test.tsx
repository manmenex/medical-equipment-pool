import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WardCorrectionAction } from "@/components/WardCorrectionAction";
import type { TransactionOut, UserProfile, Ward } from "@/types";

// Roadmap PR9B review round 2 (Findings 1 and 2): the shared action
// component -- ward-list loading/error/retry, dialog trigger, and focus
// containment/restoration -- exercised directly, independent of any one
// screen (ReturnPage/EquipmentDetailPage each get their own thinner tests
// for entry-point-specific behavior).

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
];

const listWards = vi.fn();
const correctTransactionWard = vi.fn();
const getTransaction = vi.fn();

vi.mock("@/services/masterData", () => ({
  listWards: (...args: unknown[]) => listWards(...args),
}));
vi.mock("@/services/borrow", () => ({
  correctTransactionWard: (...args: unknown[]) => correctTransactionWard(...args),
  getTransaction: (...args: unknown[]) => getTransaction(...args),
  WARD_CORRECTION_REASON_MAX_LENGTH: 500,
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

function fakeApiError(code: string, detail: string) {
  return {
    isAxiosError: true,
    response: { status: 409, data: { code, detail, status: 409 } },
  };
}

beforeEach(() => {
  mockUser = makeUser("admin");
});

afterEach(() => {
  vi.clearAllMocks();
});

function renderAction(onCorrected = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <button type="button">ปุ่มอื่นนอกไดอะล็อก</button>
      <WardCorrectionAction transaction={transaction} onCorrected={onCorrected} />
    </QueryClientProvider>
  );
  return onCorrected;
}

const TRIGGER = /แก้ไขแผนกรับเครื่อง/;
const CONFIRM_BUTTON = /ยืนยันการแก้ไข/;
const CANCEL_BUTTON = "ยกเลิก";

async function openDialog(user: ReturnType<typeof userEvent.setup>) {
  await waitFor(() => expect(screen.getByRole("button", { name: TRIGGER })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: TRIGGER }));
  await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
}

async function fillValidForm(user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(screen.getByLabelText(/แผนกที่ถูกต้อง/), "ward-2");
  await user.type(screen.getByLabelText(/เหตุผลในการแก้ไข/), "Fixed a phone-in error");
}

describe("WardCorrectionAction ward query behavior (Roadmap PR9B review round 2, Finding 1)", () => {
  it("disables the trigger while wards are loading", async () => {
    listWards.mockReturnValue(new Promise(() => {}));
    renderAction();

    const trigger = await screen.findByRole("button", { name: /กำลังโหลดรายชื่อแผนก/ });
    expect(trigger).toBeDisabled();
  });

  it("shows a visible loading state while wards are loading", async () => {
    listWards.mockReturnValue(new Promise(() => {}));
    renderAction();

    expect(await screen.findByText("กำลังโหลดรายชื่อแผนก...")).toBeInTheDocument();
  });

  it("does not open the dialog from a click while wards are still loading", async () => {
    listWards.mockReturnValue(new Promise(() => {}));
    const user = userEvent.setup();
    renderAction();

    const trigger = await screen.findByRole("button", { name: /กำลังโหลดรายชื่อแผนก/ });
    await user.click(trigger);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows an explicit error when the ward list fails to load", async () => {
    listWards.mockRejectedValue(new Error("network down"));
    renderAction();

    expect(await screen.findByText("ไม่สามารถโหลดรายชื่อแผนกได้")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("exposes a retry action on ward-list failure", async () => {
    listWards.mockRejectedValue(new Error("network down"));
    renderAction();

    expect(await screen.findByRole("button", { name: "ลองใหม่" })).toBeInTheDocument();
  });

  it("retry calls the ward query again", async () => {
    listWards.mockRejectedValue(new Error("network down"));
    const user = userEvent.setup();
    renderAction();

    await screen.findByRole("button", { name: "ลองใหม่" });
    expect(listWards).toHaveBeenCalledTimes(1);

    listWards.mockResolvedValueOnce(wards);
    await user.click(screen.getByRole("button", { name: "ลองใหม่" }));
    await waitFor(() => expect(listWards).toHaveBeenCalledTimes(2));
  });

  it("restores the normal enabled correction action after a successful retry", async () => {
    listWards.mockRejectedValueOnce(new Error("network down"));
    const user = userEvent.setup();
    renderAction();

    await screen.findByRole("button", { name: "ลองใหม่" });
    listWards.mockResolvedValueOnce(wards);
    await user.click(screen.getByRole("button", { name: "ลองใหม่" }));

    await waitFor(() => expect(screen.getByRole("button", { name: TRIGGER })).toBeEnabled());
    expect(screen.queryByText("ไม่สามารถโหลดรายชื่อแผนกได้")).not.toBeInTheDocument();
  });

  it("only opens the dialog once ward data has successfully loaded", async () => {
    listWards.mockResolvedValue(wards);
    const user = userEvent.setup();
    renderAction();

    await openDialog(user);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

describe("WardCorrectionAction keyboard and focus containment (Finding 2)", () => {
  beforeEach(() => {
    listWards.mockResolvedValue(wards);
  });

  it("focuses the first interactive element (the ward selector) when the dialog opens", async () => {
    const user = userEvent.setup();
    renderAction();
    await openDialog(user);

    expect(screen.getByLabelText(/แผนกที่ถูกต้อง/)).toHaveFocus();
  });

  it("keeps focus inside the dialog after a plain Tab from the initial focus", async () => {
    const user = userEvent.setup();
    renderAction();
    await openDialog(user);

    const dialog = screen.getByRole("dialog");
    fireEvent.keyDown(document, { key: "Tab" });
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it("Shift+Tab from the first focusable element wraps to the last", async () => {
    const user = userEvent.setup();
    renderAction();
    await openDialog(user);

    screen.getByLabelText(/แผนกที่ถูกต้อง/).focus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(screen.getByRole("button", { name: CANCEL_BUTTON })).toHaveFocus();
  });

  it("Tab from the last focusable element wraps to the first", async () => {
    const user = userEvent.setup();
    renderAction();
    await openDialog(user);

    screen.getByRole("button", { name: CANCEL_BUTTON }).focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(screen.getByLabelText(/แผนกที่ถูกต้อง/)).toHaveFocus();
  });

  it("recovers focus into the dialog when it has escaped the focusable set", async () => {
    const user = userEvent.setup();
    renderAction();
    await openDialog(user);

    screen.getByText("ปุ่มอื่นนอกไดอะล็อก").focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(screen.getByLabelText(/แผนกที่ถูกต้อง/)).toHaveFocus();
  });

  it("Escape closes the dialog safely", async () => {
    const user = userEvent.setup();
    renderAction();
    await openDialog(user);

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("Escape does not submit the form", async () => {
    const user = userEvent.setup();
    renderAction();
    await openDialog(user);
    await fillValidForm(user);

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(correctTransactionWard).not.toHaveBeenCalled();
  });

  it("returns focus to the trigger that opened the dialog after Cancel", async () => {
    const user = userEvent.setup();
    renderAction();
    await openDialog(user);

    await user.click(screen.getByRole("button", { name: CANCEL_BUTTON }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: TRIGGER })).toHaveFocus();
  });

  it("returns focus to the trigger that opened the dialog after a successful correction", async () => {
    correctTransactionWard.mockResolvedValue({ ...transaction, ward_id: "ward-2" });
    const user = userEvent.setup();
    renderAction();
    await openDialog(user);
    await fillValidForm(user);
    await user.click(screen.getByRole("button", { name: CONFIRM_BUTTON }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: TRIGGER })).toHaveFocus();
  });
});

describe("WardCorrectionAction backend error-code mapping (table-driven)", () => {
  const cases: { code: string; detail: string; expectedMessage: string }[] = [
    { code: "FORBIDDEN", detail: "Insufficient permissions", expectedMessage: "คุณไม่มีสิทธิ์แก้ไขแผนกรับเครื่อง" },
    {
      code: "TRANSACTION_NOT_FOUND",
      detail: "Transaction not found",
      expectedMessage: "ไม่พบรายการนี้แล้ว อาจมีการเปลี่ยนแปลงไปก่อนหน้านี้",
    },
    {
      code: "INVALID_INPUT",
      detail: "Ward does not exist",
      expectedMessage: "หอผู้ป่วยที่เลือกไม่ถูกต้อง กรุณาโหลดรายชื่อหอผู้ป่วยใหม่แล้วลองอีกครั้ง",
    },
    {
      code: "VALIDATION_ERROR",
      detail: "Invalid payload",
      expectedMessage: "ข้อมูลไม่ถูกต้อง กรุณาตรวจสอบแล้วลองอีกครั้ง",
    },
    {
      code: "WARD_CORRECTION_NOOP",
      detail: "Ward already recorded",
      expectedMessage: "หอผู้ป่วยที่เลือกตรงกับข้อมูลปัจจุบันอยู่แล้ว จึงไม่มีการเปลี่ยนแปลง",
    },
    {
      code: "SOME_UNDOCUMENTED_FUTURE_CODE",
      detail: "Raw backend detail text",
      expectedMessage: "Raw backend detail text",
    },
  ];

  beforeEach(() => {
    listWards.mockResolvedValue(wards);
  });

  for (const { code, detail, expectedMessage } of cases) {
    it(`maps ${code} to the expected Thai message, keeps the dialog open, and preserves the reason`, async () => {
      correctTransactionWard.mockRejectedValue(fakeApiError(code, detail));
      const onCorrected = vi.fn();
      const user = userEvent.setup();
      renderAction(onCorrected);
      await openDialog(user);
      await fillValidForm(user);
      await user.click(screen.getByRole("button", { name: CONFIRM_BUTTON }));

      await waitFor(() => expect(screen.getByText(expectedMessage)).toBeInTheDocument());
      expect(screen.getByRole("dialog")).toBeInTheDocument();
      expect(screen.getByLabelText(/เหตุผลในการแก้ไข/)).toHaveValue("Fixed a phone-in error");
      expect(onCorrected).not.toHaveBeenCalled();
      expect(getTransaction).not.toHaveBeenCalled();
    });
  }

  it("WARD_CORRECTION_CONFLICT refetches the transaction, closes the dialog, and informs the user", async () => {
    correctTransactionWard.mockRejectedValue(fakeApiError("WARD_CORRECTION_CONFLICT", "stale"));
    getTransaction.mockResolvedValue({ ...transaction, ward_id: "ward-2" });
    const onCorrected = vi.fn();
    const user = userEvent.setup();
    renderAction(onCorrected);
    await openDialog(user);
    await fillValidForm(user);
    await user.click(screen.getByRole("button", { name: CONFIRM_BUTTON }));

    await waitFor(() => expect(getTransaction).toHaveBeenCalledWith("tx-1"));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(onCorrected).toHaveBeenCalledWith(
      { ...transaction, ward_id: "ward-2" },
      expect.stringContaining("มีคำขอแก้ไขแผนกอื่นดำเนินการสำเร็จก่อนคำขอนี้")
    );
  });

  it("a validation error never produces success feedback", async () => {
    correctTransactionWard.mockRejectedValue(fakeApiError("VALIDATION_ERROR", "Invalid"));
    const onCorrected = vi.fn();
    const user = userEvent.setup();
    renderAction(onCorrected);
    await openDialog(user);
    await fillValidForm(user);
    await user.click(screen.getByRole("button", { name: CONFIRM_BUTTON }));

    await waitFor(() => expect(screen.getByText("ข้อมูลไม่ถูกต้อง กรุณาตรวจสอบแล้วลองอีกครั้ง")).toBeInTheDocument());
    expect(onCorrected).not.toHaveBeenCalled();
    expect(screen.queryByText("แก้ไขแผนกรับเครื่องสำเร็จ")).not.toBeInTheDocument();
  });
});
