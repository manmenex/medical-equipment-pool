import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TransactionCorrectionMenu } from "@/components/TransactionCorrectionMenu";
import type { TransactionOut, UserProfile } from "@/types";

const voidTransaction = vi.fn();
const changeTransactionDevice = vi.fn();
const switchTransactionAction = vi.fn();
vi.mock("@/services/borrow", () => ({
  voidTransaction: (...a: unknown[]) => voidTransaction(...a),
  changeTransactionDevice: (...a: unknown[]) => changeTransactionDevice(...a),
  switchTransactionAction: (...a: unknown[]) => switchTransactionAction(...a),
  WARD_CORRECTION_REASON_MAX_LENGTH: 500,
}));
vi.mock("@/services/equipment", () => ({
  getEquipment: async (id: string) => ({ id, bcm_code: "BCM777", asset_number: null, equipment_name: "Pump" }),
  resolveEquipmentByQr: vi.fn(),
  searchBcmSuggestions: async () => [{ id: "e-new", bcm_code: "BCM777" }],
}));
vi.mock("@/services/masterData", () => ({
  listWards: async () => [{ id: "w1", code: "W1", name: "Ward A", department_id: null }],
}));
vi.mock("@/components/QRScanner", () => ({ QRScanner: () => null }));

let role: UserProfile["role"] = "administrator";
vi.mock("@/hooks/useAuth", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useAuth")>("@/hooks/useAuth");
  return {
    ...actual,
    useAuth: () => ({
      user: { id: "u", employee_code: "U", full_name: "T", email: "t@t", role, permissions: {}, must_change_password: false },
      isAuthenticated: true,
      isLoading: false,
    }),
  };
});

function tx(over: Partial<TransactionOut>): TransactionOut {
  return {
    id: "tx1", transaction_no: "TX-1",
    equipment: { id: "e1", asset_number: null, equipment_name: "Pump", status: "issued_to_ward" },
    quantity: 1, borrowed_at: "2026-11-27T01:00:00Z", returned_at: null, borrower_name: null, ward_id: "w1",
    dispatch_type: null, routine_round: null, phone_number: null, receipt_outcome: null,
    legacy_condition_on_return: null, status: "open", notes: null, ...over,
  };
}

const onCorrected = vi.fn();
function renderMenu(t: TransactionOut) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TransactionCorrectionMenu transaction={t} onCorrected={onCorrected} />
    </QueryClientProvider>,
  );
}
async function open(user: ReturnType<typeof userEvent.setup>, item: string) {
  await user.click(screen.getByRole("button", { name: "แก้ไขรายการ" }));
  await user.click(screen.getByRole("menuitem", { name: item }));
}

beforeEach(() => {
  role = "administrator";
  voidTransaction.mockResolvedValue({});
  changeTransactionDevice.mockResolvedValue({});
  switchTransactionAction.mockResolvedValue({});
});
afterEach(() => vi.clearAllMocks());

describe("TransactionCorrectionMenu (D28 layer 3)", () => {
  it("is hidden for read-only users and for a row closed by re-dispatch", () => {
    role = "read_only";
    const { unmount } = renderMenu(tx({}));
    expect(screen.queryByRole("button", { name: "แก้ไขรายการ" })).not.toBeInTheDocument();
    unmount();
    role = "administrator";
    renderMenu(tx({ status: "closed", returned_at: null }));
    expect(screen.queryByRole("button", { name: "แก้ไขรายการ" })).not.toBeInTheDocument();
  });

  it("is offered to pool staff (the server enforces own-entry/shift with 403)", () => {
    role = "equipment_pool_staff";
    renderMenu(tx({}));
    expect(screen.getByRole("button", { name: "แก้ไขรายการ" })).toBeInTheDocument();
  });

  it("void requires a reason, then calls the endpoint and reports success", async () => {
    const user = userEvent.setup();
    renderMenu(tx({}));
    await open(user, "ยกเลิกรายการ");
    expect(screen.getByRole("button", { name: "ยืนยัน" })).toBeDisabled();
    await user.type(screen.getByLabelText("เหตุผล *"), "ลงผิดเครื่อง");
    await user.click(screen.getByRole("button", { name: "ยืนยัน" }));
    await waitFor(() => expect(voidTransaction).toHaveBeenCalledWith("tx1", "ลงผิดเครื่อง"));
    expect(onCorrected).toHaveBeenCalledWith("ยกเลิกรายการแล้ว");
  });

  it("shows the server message when the correction is refused", async () => {
    voidTransaction.mockRejectedValue({ isAxiosError: true, response: { data: { detail: "ไม่มีสิทธิ์แก้ไขรายการนี้" } } });
    const user = userEvent.setup();
    renderMenu(tx({}));
    await open(user, "ยกเลิกรายการ");
    await user.type(screen.getByLabelText("เหตุผล *"), "x");
    await user.click(screen.getByRole("button", { name: "ยืนยัน" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("ไม่มีสิทธิ์แก้ไขรายการนี้");
    expect(onCorrected).not.toHaveBeenCalled();
  });

  it("change device needs a device and a reason", async () => {
    const user = userEvent.setup();
    renderMenu(tx({}));
    await open(user, "เปลี่ยนเครื่อง");
    await user.type(screen.getByLabelText("เหตุผล *"), "สแกนผิด");
    expect(screen.getByRole("button", { name: "ยืนยัน" })).toBeDisabled();
    await user.type(screen.getByLabelText("รหัส BCM"), "BCM777{Enter}");
    await screen.findByText("BCM777");
    await user.click(screen.getByRole("button", { name: "ยืนยัน" }));
    await waitFor(() =>
      expect(changeTransactionDevice).toHaveBeenCalledWith("tx1", { reason: "สแกนผิด", equipment_id: "e-new" }),
    );
  });

  it("switch dispatch to receipt defaults to usable and can pick defective", async () => {
    const user = userEvent.setup();
    renderMenu(tx({}));
    await open(user, "สลับงาน");
    expect(screen.getByRole("button", { name: "ใช้งานได้" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "เสีย" }));
    await user.type(screen.getByLabelText("เหตุผล *"), "ที่จริงคือรับคืน");
    await user.click(screen.getByRole("button", { name: "ยืนยัน" }));
    await waitFor(() =>
      expect(switchTransactionAction).toHaveBeenCalledWith("tx1", { reason: "ที่จริงคือรับคืน", outcome: "defective" }),
    );
  });

  it("switch receipt to dispatch requires a ward", async () => {
    const user = userEvent.setup();
    renderMenu(tx({ status: "closed", returned_at: "2026-11-27T02:00:00Z", receipt_outcome: "usable" }));
    await open(user, "สลับงาน");
    await user.type(screen.getByLabelText("เหตุผล *"), "ที่จริงคือเบิก");
    expect(screen.getByRole("button", { name: "ยืนยัน" })).toBeDisabled();
    await user.selectOptions(await screen.findByLabelText(/หอผู้ป่วย/), "w1");
    await user.click(screen.getByRole("button", { name: "ยืนยัน" }));
    await waitFor(() =>
      expect(switchTransactionAction).toHaveBeenCalledWith("tx1", { reason: "ที่จริงคือเบิก", ward_id: "w1" }),
    );
  });
});
