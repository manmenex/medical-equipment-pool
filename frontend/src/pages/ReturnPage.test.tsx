import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReturnPage } from "@/pages/ReturnPage";
import { useUiStore } from "@/store/uiStore";
import type { Equipment, TransactionOut, Ward } from "@/types";

// Roadmap PR27/PR28 ward-first receipt screen (docs/api/ward-first-entry.md).
function equipment(id: string, bcm: string, name: string): Equipment {
  return {
    id, asset_number: null, serial_number: null, equipment_name: name, category_id: null, brand: null, model: null,
    department_owner_id: null, current_location_id: null, status: "issued_to_ward", bcm_code: bcm,
    pm_due_date: null, cal_due_date: null, created_at: "", updated_at: "",
  };
}
const EQ: Record<string, Equipment> = {
  BCM001: equipment("e1", "BCM001", "Infusion Pump"),
  BCM002: equipment("e2", "BCM002", "Ventilator"),
  CRYO1: equipment("c1", "CRYO1", "Cryo-Cuff"),
  FREE1: equipment("f1", "FREE1", "Free Pump"),
};

function tx(id: string, eq: Equipment, ward = "ward-1", extra: Partial<TransactionOut> = {}): TransactionOut {
  return {
    id, transaction_no: `TX-${id}`,
    equipment: { id: eq.id, asset_number: null, equipment_name: eq.equipment_name, status: "issued_to_ward" },
    quantity: 1, borrowed_at: "2026-11-25T01:00:00Z", returned_at: null, borrower_name: null, ward_id: ward,
    dispatch_type: null, routine_round: null, phone_number: null, receipt_outcome: null, legacy_condition_on_return: null,
    status: "open", notes: null, ...extra,
  };
}
const ISSUED = { back_hip_rib: 0, knee: 2, shoulder: 0, ankle: 1 };
let active: TransactionOut[] = [];

const wards: Ward[] = [
  { id: "ward-1", code: "W1", name: "Ward A", department_id: null },
  { id: "ward-2", code: "W2", name: "Ward B", department_id: null },
];

const getEquipment = vi.fn();
const resolveEquipmentByQr = vi.fn();
const searchBcmSuggestions = vi.fn();
const getDispatchCheck = vi.fn();
const listActiveBorrows = vi.fn();
const receiptBatch = vi.fn();

vi.mock("@/services/equipment", () => ({
  getEquipment: (...a: unknown[]) => getEquipment(...a),
  resolveEquipmentByQr: (...a: unknown[]) => resolveEquipmentByQr(...a),
  searchBcmSuggestions: (...a: unknown[]) => searchBcmSuggestions(...a),
  getDispatchCheck: (...a: unknown[]) => getDispatchCheck(...a),
}));
vi.mock("@/services/borrow", () => ({
  listActiveBorrows: (...a: unknown[]) => listActiveBorrows(...a),
  receiptBatch: (...a: unknown[]) => receiptBatch(...a),
}));
vi.mock("@/services/masterData", () => ({
  listWards: () => Promise.resolve(wards),
  listDepartments: () => Promise.resolve([]),
}));
vi.mock("@/services/cuffs", () => ({
  getOutstandingCuffs: () => Promise.resolve({ total_outstanding: 0, items: [] }),
  receiveCuffs: vi.fn(),
}));
vi.mock("@/components/QRScanner", () => ({ QRScanner: () => null }));

beforeEach(() => {
  active = [
    tx("t1", EQ.BCM001, "ward-1"),
    tx("t2", EQ.BCM002, "ward-2"),
    tx("tc", EQ.CRYO1, "ward-1", { checklist_kind: "cryo_cuff", dispatch_checks: { kind: "cryo_cuff", body_ok: true, charger_ok: true, lid_with_charger_ok: true, lid_without_charger_ok: true, hose_oring_ok: true, cuff_ok: true, cuffs: ISSUED } }),
  ];
  listActiveBorrows.mockImplementation(async () => active);
  getEquipment.mockImplementation(async (id: string) => Object.values(EQ).find((e) => e.id === id));
  searchBcmSuggestions.mockImplementation(async (q: string) =>
    Object.values(EQ).filter((e) => e.bcm_code!.toLowerCase().includes(q.toLowerCase())).map((e) => ({ id: e.id, bcm_code: e.bcm_code! })),
  );
  getDispatchCheck.mockResolvedValue({ checklist_kind: "standard" });
  receiptBatch.mockImplementation(async (p: { items: unknown[] }) => ({
    total: p.items.length, succeeded: p.items.length, failed: 0,
    results: p.items.map((_, index) => ({ index, ok: true, equipment_id: null, transaction_id: "x", transaction_no: `RX-${index + 1}`, cuffs_outstanding: null, error: null })),
  }));
  useUiStore.setState({ lastWard: null, wardUsage: {} });
});
afterEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
});

function renderPage(entry = "/return") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}>
        <ReturnPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
const addBcm = (user: ReturnType<typeof userEvent.setup>, bcm: string) => user.type(screen.getByLabelText("รหัส BCM"), `${bcm}{Enter}`);

async function pickWard(user: ReturnType<typeof userEvent.setup>, query: string) {
  await user.type(await screen.findByLabelText("ค้นหาหอผู้ป่วย"), query);
  await user.click(within(await screen.findByRole("listbox")).getByRole("button"));
}

describe("receipt screen", () => {
  it("uses the receipt wording, and adds a compact row from a BCM scan", async () => {
    const user = userEvent.setup();
    renderPage();
    expect(screen.getByRole("heading", { name: "หอผู้ป่วยที่ส่งคืน" })).toBeInTheDocument();
    expect(screen.getByLabelText("ชื่อผู้ส่งคืน (Ward)")).toBeInTheDocument();
    await addBcm(user, "BCM001");
    expect(await screen.findByRole("button", { name: "แก้ไข BCM001" })).toHaveTextContent("✓✓✓");
    expect(screen.getByRole("heading", { name: "สแกนเครื่อง (1 เครื่อง)" })).toBeInTheDocument();
  });

  it("shows a red notice and adds nothing for equipment that was never dispatched", async () => {
    const user = userEvent.setup();
    renderPage();
    await addBcm(user, "FREE1");
    expect(await screen.findByRole("alert")).toHaveTextContent("⛔ FREE1 ไม่ได้ถูกจ่ายออกไป ไม่ถูกเพิ่ม");
    expect(screen.getByRole("heading", { name: "สแกนเครื่อง (0 เครื่อง)" })).toBeInTheDocument();
  });

  it("refetches the open-transaction list ONCE before saying a scanned device was not dispatched", async () => {
    // First answer is stale (no FREE1 yet); the forced refetch sees the new dispatch.
    listActiveBorrows.mockImplementationOnce(async () => active);
    const withFree = [...active, tx("tf", EQ.FREE1, "ward-1")];
    listActiveBorrows.mockImplementationOnce(async () => withFree);
    const user = userEvent.setup();
    renderPage();
    await addBcm(user, "FREE1");
    expect(await screen.findByRole("button", { name: "แก้ไข FREE1" })).toBeInTheDocument();
    expect(listActiveBorrows).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("still reports 'not dispatched' after exactly one forced refetch", async () => {
    const user = userEvent.setup();
    renderPage();
    await addBcm(user, "FREE1");
    expect(await screen.findByRole("alert")).toHaveTextContent("ไม่ได้ถูกจ่ายออกไป");
    expect(listActiveBorrows).toHaveBeenCalledTimes(2);
  });

  it("receives from ANY ward without a warning and sends the default usable payload", async () => {
    const user = userEvent.setup();
    renderPage();
    await pickWard(user, "Ward A");
    await user.type(screen.getByLabelText("ชื่อผู้ส่งคืน (Ward)"), "คุณมาลี");
    await addBcm(user, "BCM002"); // dispatched to Ward B, returned by Ward A
    await screen.findByRole("button", { name: "แก้ไข BCM002" });
    expect(screen.queryByText(/ค้าง Ward|ต่างหอ|ไม่ใช่หอ/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "ยืนยันการรับคืน (1 เครื่อง)" }));
    await waitFor(() => expect(receiptBatch).toHaveBeenCalled());
    expect(receiptBatch.mock.calls[0][0]).toEqual({
      ward_id: "ward-1",
      ward_contact_name: "คุณมาลี",
      note: null,
      items: [{
        transaction_id: "t2", receipt_outcome: "usable",
        checks: { kind: "standard", screen_ok: true, charger_ok: true, clamp_ok: true }, cuffs_returned: null,
      }],
    });
    expect(await screen.findByText("✓ BCM002 (RX-1)")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "สแกนเครื่อง (0 เครื่อง)" })).toBeInTheDocument();
  });

  it("prompts (without auto-changing) when a check is unchecked while the outcome is usable", async () => {
    const user = userEvent.setup();
    renderPage();
    await addBcm(user, "BCM001");
    await user.click(await screen.findByRole("button", { name: "แก้ไข BCM001" }));
    const panel = screen.getByRole("group", { name: "แก้ไข BCM001" });
    expect(within(panel).getByRole("button", { name: "ใช้งานได้" })).toHaveAttribute("aria-pressed", "true");
    expect(within(panel).queryByText(/มีรายการไม่ปกติ/)).not.toBeInTheDocument();

    await user.click(within(panel).getByLabelText("Pole Clamp ไม่แตกหัก"));
    expect(within(panel).getByRole("alert")).toHaveTextContent('มีรายการไม่ปกติ – จะเปลี่ยนผลเป็น "เสีย" ไหม?');
    expect(within(panel).getByRole("button", { name: "ใช้งานได้" })).toHaveAttribute("aria-pressed", "true"); // not auto-changed

    await user.click(within(panel).getByRole("button", { name: 'เปลี่ยนเป็น "เสีย"' }));
    expect(within(panel).getByRole("button", { name: "เสีย" })).toHaveAttribute("aria-pressed", "true");
    expect(within(panel).queryByText(/มีรายการไม่ปกติ/)).not.toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "เสร็จ" }));
    expect(screen.getByRole("button", { name: "แก้ไข BCM001" })).toHaveTextContent("เสีย");
  });

  it("Cryo-Cuff: cuffs returned default to the issued counts and a reduced count is sent as a partial return", async () => {
    const user = userEvent.setup();
    renderPage();
    await addBcm(user, "CRYO1");
    await user.click(await screen.findByRole("button", { name: "แก้ไข CRYO1" }));
    const panel = screen.getByRole("group", { name: "แก้ไข CRYO1" });
    expect(within(panel).getAllByRole("listitem")).toHaveLength(6);
    expect(within(panel).getByLabelText("จำนวน Knee")).toHaveValue(2);
    expect(within(panel).getByLabelText("จำนวน Ankle")).toHaveValue(1);
    expect(within(panel).getByLabelText("จำนวน Shoulder")).toBeDisabled(); // none issued

    await user.clear(within(panel).getByLabelText("จำนวน Knee"));
    await user.type(within(panel).getByLabelText("จำนวน Knee"), "1");
    await user.click(within(panel).getByRole("button", { name: "เสร็จ" }));
    expect(screen.getByRole("button", { name: "แก้ไข CRYO1" })).toHaveTextContent("Cuff 2/3");

    await user.click(screen.getByRole("button", { name: "ยืนยันการรับคืน (1 เครื่อง)" }));
    await waitFor(() => expect(receiptBatch).toHaveBeenCalled());
    const item = receiptBatch.mock.calls[0][0].items[0];
    expect(item.transaction_id).toBe("tc");
    expect(item.cuffs_returned).toEqual({ back_hip_rib: 0, knee: 1, shoulder: 0, ankle: 1 });
    expect(item.checks).toMatchObject({ kind: "cryo_cuff", cuffs: { knee: 1, ankle: 1 } });
  });

  it("caps the returned count at the issued count and supports a device-only receipt (all zero)", async () => {
    const user = userEvent.setup();
    renderPage();
    await addBcm(user, "CRYO1");
    await user.click(await screen.findByRole("button", { name: "แก้ไข CRYO1" }));
    const panel = screen.getByRole("group", { name: "แก้ไข CRYO1" });
    await user.clear(within(panel).getByLabelText("จำนวน Knee"));
    await user.type(within(panel).getByLabelText("จำนวน Knee"), "9");
    expect(within(panel).getByLabelText("จำนวน Knee")).toHaveValue(2);
    await user.click(within(panel).getByLabelText("Knee"));
    await user.click(within(panel).getByLabelText("Ankle"));
    await user.click(within(panel).getByRole("button", { name: "เสร็จ" }));
    await user.click(screen.getByRole("button", { name: "ยืนยันการรับคืน (1 เครื่อง)" }));
    await waitFor(() => expect(receiptBatch).toHaveBeenCalled());
    expect(receiptBatch.mock.calls[0][0].items[0].cuffs_returned).toEqual({ back_hip_rib: 0, knee: 0, shoulder: 0, ankle: 0 });
  });

  it("keeps failed items with a Thai message and clears succeeded ones", async () => {
    receiptBatch.mockResolvedValueOnce({
      total: 2, succeeded: 1, failed: 1,
      results: [
        { index: 0, ok: true, equipment_id: "e1", transaction_id: "t1", transaction_no: "RX-9", cuffs_outstanding: null, error: null },
        { index: 1, ok: false, equipment_id: "c1", transaction_id: null, transaction_no: null, cuffs_outstanding: null,
          error: { code: "CUFF_RETURN_EXCEEDS_OUTSTANDING", message: "m", status: 409 } },
      ],
    });
    const user = userEvent.setup();
    renderPage();
    await addBcm(user, "BCM001");
    await addBcm(user, "CRYO1");
    await screen.findByRole("button", { name: "แก้ไข CRYO1" });
    await user.click(screen.getByRole("button", { name: "ยืนยันการรับคืน (2 เครื่อง)" }));
    expect(await screen.findByText("✓ BCM001 (RX-9)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "แก้ไข BCM001" })).not.toBeInTheDocument();
    expect(screen.getByText(/CRYO1: จำนวน Cuff ที่รับคืนมากกว่า/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "แก้ไข CRYO1" })).toBeInTheDocument();
  });

  it("lists the selected ward's open transactions in an expandable section; tapping adds the item", async () => {
    const user = userEvent.setup();
    renderPage();
    await pickWard(user, "Ward A");
    const toggle = await screen.findByRole("button", { name: /เครื่องที่ค้างอยู่ Ward A \(2\)/ });
    await user.click(toggle);
    expect(screen.queryByText("Ventilator")).not.toBeInTheDocument(); // Ward B's
    await user.click(screen.getByRole("button", { name: "เพิ่ม Infusion Pump" }));
    expect(await screen.findByRole("button", { name: "แก้ไข BCM001" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /เครื่องที่ค้างอยู่ Ward A \(1\)/ })).toBeInTheDocument();
  });

  it("offers the outstanding-cuffs tab", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("tab", { name: "รับ Cuff ค้าง" }));
    expect(await screen.findByText("ไม่มี Cuff ค้าง")).toBeInTheDocument();
  });
});

describe("review fixes", () => {
  it("hides the phone field (the receipt API takes no phone)", async () => {
    renderPage();
    expect(await screen.findByLabelText("ชื่อผู้ส่งคืน (Ward)")).toBeInTheDocument();
    expect(screen.queryByLabelText("เบอร์โทร")).not.toBeInTheDocument();
  });

  it("fetches the open-transaction list once for several scans (cached query data)", async () => {
    const user = userEvent.setup();
    renderPage();
    await addBcm(user, "BCM001");
    await screen.findByRole("button", { name: "แก้ไข BCM001" });
    await addBcm(user, "BCM002");
    await screen.findByRole("button", { name: "แก้ไข BCM002" });
    expect(listActiveBorrows).toHaveBeenCalledTimes(1);
  });

  it("ignores a second confirm while a submit is in flight (ref guard)", async () => {
    let release: (v: unknown) => void = () => undefined;
    receiptBatch.mockImplementationOnce(
      () =>
        new Promise((res) => {
          release = res;
        }),
    );
    const user = userEvent.setup();
    renderPage();
    await addBcm(user, "BCM001");
    await screen.findByRole("button", { name: "แก้ไข BCM001" });
    await user.dblClick(screen.getByRole("button", { name: "ยืนยันการรับคืน (1 เครื่อง)" }));
    expect(receiptBatch).toHaveBeenCalledTimes(1);
    release({ total: 1, succeeded: 1, failed: 0, results: [{ index: 0, ok: true, equipment_id: "e1", transaction_id: "t1", transaction_no: "RX-1", cuffs_outstanding: null, error: null }] });
    expect(await screen.findByText("✓ BCM001 (RX-1)")).toBeInTheDocument();
  });
});
