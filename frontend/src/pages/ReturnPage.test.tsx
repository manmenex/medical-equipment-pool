import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReturnPage } from "@/pages/ReturnPage";
import type { TransactionOut } from "@/types";

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

const listActiveBorrows = vi.fn();
const createReturn = vi.fn();

// Roadmap PR8B: this endpoint's receipt_outcome field is the subject under
// test -- the QR scanner and BCM search inputs are unrelated dependencies
// (camera access, debounced network search) that would otherwise make this
// a QRScanner/BcmSearchInput test, not a ReturnPage receipt-contract test.
vi.mock("@/services/borrow", () => ({
  listActiveBorrows: (...args: unknown[]) => listActiveBorrows(...args),
  createReturn: (...args: unknown[]) => createReturn(...args),
}));
vi.mock("@/components/QRScanner", () => ({ QRScanner: () => null }));
vi.mock("@/components/BcmSearchInput", () => ({ BcmSearchInput: () => null }));

afterEach(() => {
  vi.clearAllMocks();
});

function renderReturnPage() {
  return render(
    <MemoryRouter initialEntries={["/return?equipment_id=eq-1"]}>
      <ReturnPage />
    </MemoryRouter>
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
