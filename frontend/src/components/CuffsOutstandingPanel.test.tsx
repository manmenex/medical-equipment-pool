import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CuffsOutstandingPanel } from "@/components/CuffsOutstandingPanel";

const getOutstandingCuffs = vi.fn();
const receiveCuffs = vi.fn();
vi.mock("@/services/cuffs", () => ({
  getOutstandingCuffs: (...a: unknown[]) => getOutstandingCuffs(...a),
  receiveCuffs: (...a: unknown[]) => receiveCuffs(...a),
}));
vi.mock("@/services/equipment", () => ({ resolveEquipmentByQr: vi.fn() }));
vi.mock("@/components/QRScanner", () => ({ QRScanner: () => null }));

const zero = { back_hip_rib: 0, knee: 0, shoulder: 0, ankle: 0 };
const data = {
  total_outstanding: 3,
  items: [{
    ward_id: "w1", ward_name: "Ward A", cuffs: { ...zero, knee: 2, ankle: 1 }, total: 3,
    transactions: [
      { transaction_id: "t1", transaction_no: "TX-1", equipment_id: "e1", bcm_code: "BCM-1", equipment_name: "Cryo", dispatched_at: "", device_received: true, cuffs: { ...zero, knee: 2, ankle: 1 } },
      { transaction_id: "t2", transaction_no: "TX-2", equipment_id: "e2", bcm_code: "BCM-2", equipment_name: "Cryo", dispatched_at: "", device_received: false, cuffs: { ...zero, knee: 1 } },
    ],
  }],
};

afterEach(() => vi.clearAllMocks());

function renderPanel(props: { readOnly?: boolean } = {}) {
  getOutstandingCuffs.mockResolvedValue(data);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <CuffsOutstandingPanel {...props} />
    </QueryClientProvider>,
  );
}

describe("CuffsOutstandingPanel", () => {
  it("lists outstanding cuffs grouped by ward and receives a partial count via receive-cuffs", async () => {
    const user = userEvent.setup();
    receiveCuffs.mockResolvedValue({});
    renderPanel();
    expect(await screen.findByRole("heading", { name: /Ward A/ })).toHaveTextContent("Knee 2 · Ankle 1 · รวม 3");
    await user.click(screen.getByRole("button", { name: "รับ Cuff BCM-1" }));
    const panel = screen.getByRole("group", { name: "รับ Cuff BCM-1" });
    expect(within(panel).getByLabelText("จำนวน Knee")).toHaveValue(2);
    await user.clear(within(panel).getByLabelText("จำนวน Knee"));
    await user.type(within(panel).getByLabelText("จำนวน Knee"), "1");
    await user.type(within(panel).getByLabelText("ชื่อผู้ส่งคืน"), "คุณมาลี");
    await user.click(within(panel).getByRole("button", { name: "บันทึกรับ Cuff" }));
    await waitFor(() => expect(receiveCuffs).toHaveBeenCalledWith("t1", { knee: 1, ankle: 1 }, "คุณมาลี"));
    expect(await screen.findByText("✓ รับ Cuff แล้ว")).toBeInTheDocument();
  });

  it("explains that a device still out must be received with its cuffs", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(await screen.findByRole("button", { name: "รับ Cuff BCM-2" }));
    expect(screen.getByText(/ยังไม่รับคืนเครื่อง/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "บันทึกรับ Cuff" })).not.toBeInTheDocument();
  });

  it("shows a Thai message for a rejected receive", async () => {
    const user = userEvent.setup();
    receiveCuffs.mockRejectedValue({ isAxiosError: true, response: { status: 409, data: { code: "CUFF_RETURN_EXCEEDS_OUTSTANDING", detail: "x" } } });
    renderPanel();
    await user.click(await screen.findByRole("button", { name: "รับ Cuff BCM-1" }));
    await user.click(screen.getByRole("button", { name: "บันทึกรับ Cuff" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("filters by BCM text", async () => {
    const user = userEvent.setup();
    renderPanel();
    await screen.findByRole("button", { name: "รับ Cuff BCM-1" });
    await user.type(screen.getByLabelText("รหัส BCM"), "BCM-2{Enter}");
    expect(screen.queryByRole("button", { name: "รับ Cuff BCM-1" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "รับ Cuff BCM-2" })).toBeInTheDocument();
  });

  it("read-only mode (Monitor) lists without any receive actions", async () => {
    renderPanel({ readOnly: true });
    expect(await screen.findByText("BCM-1")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /รับ Cuff/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("รหัส BCM")).not.toBeInTheDocument();
  });
});
