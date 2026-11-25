import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BorrowPage } from "@/pages/BorrowPage";
import type { DispatchCheck } from "@/services/equipment";
import { useUiStore } from "@/store/uiStore";
import type { Equipment, Ward } from "@/types";

// Roadmap PR27/PR28 ward-first dispatch screen (docs/api/ward-first-entry.md).
function equipment(id: string, bcm: string, name = "Infusion Pump"): Equipment {
  return {
    id,
    asset_number: null,
    serial_number: null,
    equipment_name: name,
    category_id: null,
    brand: null,
    model: null,
    department_owner_id: null,
    current_location_id: null,
    status: "available_at_pool",
    bcm_code: bcm,
    pm_due_date: null,
    cal_due_date: null,
    created_at: "",
    updated_at: "",
  };
}

const EQ: Record<string, Equipment> = {
  BCM001: equipment("e1", "BCM001"),
  BCM002: equipment("e2", "BCM002", "Ventilator"),
  BCM900: equipment("e9", "BCM900", "Old Pump"),
  CRYO1: equipment("c1", "CRYO1", "Cryo-Cuff"),
};
let checkFor: Record<string, Partial<DispatchCheck>> = {};

function plainCheck(id: string): DispatchCheck {
  return {
    equipment_id: id,
    status: "available_at_pool",
    warning: null,
    dispatchable: true,
    requires_acknowledgement: false,
    current_ward_id: null,
    current_ward_name: null,
    dispatched_at: null,
    open_transaction_id: null,
    open_transaction_no: null,
    checklist_kind: "standard",
    ...checkFor[id],
  };
}

const wards: Ward[] = [
  { id: "ward-1", code: "W1", name: "Ward A", department_id: null, phone: "1111" },
  { id: "ward-2", code: "W2", name: "Ward B", department_id: "d1", phone: null },
];

const getEquipment = vi.fn();
const resolveEquipmentByQr = vi.fn();
const searchBcmSuggestions = vi.fn();
const getDispatchCheck = vi.fn();
const dispatchBatch = vi.fn();

vi.mock("@/services/equipment", () => ({
  getEquipment: (...a: unknown[]) => getEquipment(...a),
  resolveEquipmentByQr: (...a: unknown[]) => resolveEquipmentByQr(...a),
  searchBcmSuggestions: (...a: unknown[]) => searchBcmSuggestions(...a),
  getDispatchCheck: (...a: unknown[]) => getDispatchCheck(...a),
}));
vi.mock("@/services/borrow", () => ({ dispatchBatch: (...a: unknown[]) => dispatchBatch(...a) }));
vi.mock("@/services/masterData", () => ({
  listWards: () => Promise.resolve(wards),
  listDepartments: () => Promise.resolve([{ id: "d1", code: "D1", name: "Dept", phone: "2222" }]),
}));
vi.mock("@/components/QRScanner", () => ({
  QRScanner: ({ onScan }: { onScan: (t: string) => void }) => (
    <button type="button" onClick={() => onScan("QR-RAW-1")}>
      fake-qr-frame
    </button>
  ),
}));

beforeEach(() => {
  checkFor = {};
  getEquipment.mockImplementation(async (id: string) => Object.values(EQ).find((e) => e.id === id));
  searchBcmSuggestions.mockImplementation(async (q: string) =>
    Object.values(EQ)
      .filter((e) => e.bcm_code!.toLowerCase().includes(q.toLowerCase()))
      .map((e) => ({ id: e.id, bcm_code: e.bcm_code! })),
  );
  resolveEquipmentByQr.mockResolvedValue(EQ.BCM002);
  getDispatchCheck.mockImplementation(async (id: string) => plainCheck(id));
  dispatchBatch.mockImplementation(async (p: { items: unknown[] }) => ({
    total: p.items.length,
    succeeded: p.items.length,
    failed: 0,
    results: p.items.map((_, index) => ({
      index, ok: true, equipment_id: null, transaction_id: `t${index}`, transaction_no: `TX-${index + 1}`,
      cuffs_outstanding: null, error: null,
    })),
  }));
  useUiStore.setState({ lastWard: null, wardUsage: {} });
});
afterEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
});

function renderPage(entry = "/borrow") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}>
        <BorrowPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function pickWard(user: ReturnType<typeof userEvent.setup>, query: string) {
  await user.type(await screen.findByLabelText("ค้นหาหอผู้ป่วย"), query);
  const box = await screen.findByRole("listbox");
  await user.click(within(box).getByRole("button"));
}

async function addBcm(user: ReturnType<typeof userEvent.setup>, bcm: string) {
  await user.type(screen.getByLabelText("รหัส BCM"), `${bcm}{Enter}`);
}

describe("dispatch screen layout", () => {
  it("shows the 3 sections, shift chip, note input and no HN field", async () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "หอผู้ป่วย" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "สแกนเครื่อง (0 เครื่อง)" })).toBeInTheDocument();
    expect(screen.getByTestId("shift-chip")).toHaveTextContent(/^(Day|Night) · \d{2}:\d{2}$/);
    expect(screen.getByLabelText("ชื่อผู้รับ (Ward)")).toBeInTheDocument();
    expect(screen.getByLabelText("หมายเหตุ (ไม่บังคับ)")).toBeInTheDocument();
    expect(screen.getByText("เวลาและกะบันทึกอัตโนมัติ")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ยืนยันการเบิก (0 เครื่อง)" })).toBeDisabled();
    expect(screen.queryByText(/HN/)).not.toBeInTheDocument();
  });

  it("prefills the phone from the ward (department fallback) and keeps it editable", async () => {
    const user = userEvent.setup();
    renderPage();
    await pickWard(user, "Ward A");
    expect(screen.getByLabelText("เบอร์โทร")).toHaveValue("1111");
    await user.clear(screen.getByLabelText("เบอร์โทร"));
    await user.type(screen.getByLabelText("เบอร์โทร"), "9999");
    expect(screen.getByLabelText("เบอร์โทร")).toHaveValue("9999");
    await user.clear(screen.getByLabelText("ค้นหาหอผู้ป่วย"));
    await pickWard(user, "Ward B");
    expect(screen.getByLabelText("เบอร์โทร")).toHaveValue("2222");
  });

  it("shows the most used wards as chips from local history", async () => {
    useUiStore.setState({ wardUsage: { "ward-2": 5, "ward-1": 1 } });
    renderPage();
    const b = await screen.findByRole("button", { name: "Ward B" });
    const a = screen.getByRole("button", { name: "Ward A" });
    expect(b.compareDocumentPosition(a) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy(); // most used first
  });
});

describe("scan flow", () => {
  it("adds a compact row per scan (dispatch-check called), ignores duplicates", async () => {
    const user = userEvent.setup();
    renderPage();
    await addBcm(user, "BCM001");
    const row = await screen.findByRole("button", { name: "แก้ไข BCM001" });
    expect(row).toHaveTextContent("BCM001");
    expect(row).toHaveTextContent("Infusion Pump");
    expect(row).toHaveTextContent("✓✓✓");
    expect(screen.getByRole("heading", { name: "สแกนเครื่อง (1 เครื่อง)" })).toBeInTheDocument();

    await addBcm(user, "BCM001");
    await waitFor(() => expect(searchBcmSuggestions).toHaveBeenCalledTimes(2));
    expect(screen.getAllByRole("button", { name: "แก้ไข BCM001" })).toHaveLength(1);
    expect(getDispatchCheck).toHaveBeenCalledTimes(1);
  });

  it("adds from a QR scan and drops repeated frames of the same code", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "สแกน QR" }));
    await user.click(screen.getByRole("button", { name: "fake-qr-frame" }));
    await user.click(screen.getByRole("button", { name: "fake-qr-frame" }));
    expect(await screen.findByRole("button", { name: "แก้ไข BCM002" })).toBeInTheDocument();
    expect(resolveEquipmentByQr).toHaveBeenCalledTimes(1);
  });

  it("shows a red notice for decommissioned and unknown equipment and does not add them", async () => {
    checkFor.e9 = { status: "decommissioned", warning: "decommissioned", dispatchable: false };
    const user = userEvent.setup();
    renderPage();
    await addBcm(user, "BCM900");
    expect(await screen.findByRole("alert")).toHaveTextContent("⛔ BCM900 ปลดระวางแล้ว ไม่ถูกเพิ่ม");
    await addBcm(user, "NOPE");
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("⛔ ไม่พบเครื่อง NOPE ไม่ถูกเพิ่ม"));
    expect(screen.getByRole("heading", { name: "สแกนเครื่อง (0 เครื่อง)" })).toBeInTheDocument();
  });
});

describe("status warnings (PR31) and acknowledgement payload", () => {
  it("shows amber warning rows and sends acknowledge + expected_* from dispatch-check", async () => {
    checkFor.e1 = {
      status: "issued_to_ward", warning: "already_dispatched", requires_acknowledgement: true,
      current_ward_name: "Ward Z", open_transaction_id: "tx-open", open_transaction_no: "TX-OLD",
    };
    checkFor.e2 = { status: "unavailable_defective", warning: "defective", requires_acknowledgement: true };
    const user = userEvent.setup();
    renderPage();
    await pickWard(user, "Ward A");
    await addBcm(user, "BCM001");
    await addBcm(user, "BCM002");
    expect(await screen.findByRole("button", { name: "แก้ไข BCM001" })).toHaveTextContent("⚠ ค้าง Ward Z");
    expect(await screen.findByRole("button", { name: "แก้ไข BCM002" })).toHaveTextContent("⚠ เสีย");

    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก (2 เครื่อง)" }));
    await waitFor(() => expect(dispatchBatch).toHaveBeenCalledTimes(1));
    const std = { kind: "standard", screen_ok: true, charger_ok: true, clamp_ok: true };
    expect(dispatchBatch.mock.calls[0][0].items).toEqual([
      {
        equipment_id: "e1", checks: std, acknowledge_status_warning: true,
        expected_open_transaction_id: "tx-open", expected_status: "issued_to_ward",
      },
      {
        equipment_id: "e2", checks: std, acknowledge_status_warning: true,
        expected_open_transaction_id: null, expected_status: "unavailable_defective",
      },
    ]);
  });

  it("shows the warning text inside the edit panel", async () => {
    checkFor.e1 = { status: "issued_to_ward", warning: "already_dispatched", current_ward_name: "Ward Z", open_transaction_id: "tx-open" };
    const user = userEvent.setup();
    renderPage();
    await addBcm(user, "BCM001");
    await user.click(await screen.findByRole("button", { name: "แก้ไข BCM001" }));
    expect(screen.getByRole("group", { name: "แก้ไข BCM001" })).toHaveTextContent(/ถูกจ่ายไป Ward Z ยังไม่บันทึกรับคืน/);
  });
});

describe("edit panel and checks", () => {
  it("opens an inline panel with 3 default-checked boxes; unchecking one is sent and shown as ✗; done closes it", async () => {
    const user = userEvent.setup();
    renderPage();
    await pickWard(user, "Ward A");
    await user.type(screen.getByLabelText("ชื่อผู้รับ (Ward)"), "คุณสมศรี");
    await user.type(screen.getByLabelText("หมายเหตุ (ไม่บังคับ)"), "ด่วน");
    await addBcm(user, "BCM001");
    await user.click(await screen.findByRole("button", { name: "แก้ไข BCM001" }));

    const panel = screen.getByRole("group", { name: "แก้ไข BCM001" });
    for (const label of ["หน้าจอไม่แตกร้าว", "สายชาร์จไม่ขาด", "Pole Clamp ไม่แตกหัก"]) {
      expect(within(panel).getByLabelText(label)).toBeChecked();
    }
    expect(within(panel).getByRole("button", { name: "ลบออก" })).toBeInTheDocument();
    await user.click(within(panel).getByLabelText("สายชาร์จไม่ขาด"));
    await user.click(within(panel).getByRole("button", { name: "เสร็จ" }));
    expect(screen.queryByRole("group", { name: "แก้ไข BCM001" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "แก้ไข BCM001" })).toHaveTextContent("✓✗✓");

    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก (1 เครื่อง)" }));
    await waitFor(() => expect(dispatchBatch).toHaveBeenCalled());
    expect(dispatchBatch.mock.calls[0][0]).toEqual({
      ward_id: "ward-1",
      ward_contact_name: "คุณสมศรี",
      phone: "1111",
      note: "ด่วน",
      items: [{ equipment_id: "e1", checks: { kind: "standard", screen_ok: true, charger_ok: false, clamp_ok: true } }],
    });
  });

  it("removes an item with ลบออก", async () => {
    const user = userEvent.setup();
    renderPage();
    await addBcm(user, "BCM001");
    await user.click(await screen.findByRole("button", { name: "แก้ไข BCM001" }));
    await user.click(screen.getByRole("button", { name: "ลบออก" }));
    expect(screen.queryByRole("button", { name: "แก้ไข BCM001" })).not.toBeInTheDocument();
  });

  it("renders the exact 6-item Cryo-Cuff form and sends the cryo payload with cuff counts", async () => {
    checkFor.c1 = { checklist_kind: "cryo_cuff" };
    const user = userEvent.setup();
    renderPage();
    await pickWard(user, "Ward A");
    await addBcm(user, "CRYO1");
    await user.click(await screen.findByRole("button", { name: "แก้ไข CRYO1" }));
    const panel = screen.getByRole("group", { name: "แก้ไข CRYO1" });

    expect(within(panel).getAllByRole("listitem")).toHaveLength(6);
    for (const text of [
      "1 ตัวเครื่อง ×1", "(ไม่แตกหัก เสียหาย)", "2 สายชาร์จ ×1", "3 ฝาปิดตัวเครื่อง แบบมีสายชาร์จ ×1",
      "4 ฝาปิดตัวเครื่อง แบบไม่มีสายชาร์จ ×1", "5 สายท่อน้ำและ O-Ring ×1", "(O-Ring บริเวณปลาย Hose ทั้งสองข้าง)",
      "6 Cuff", "(สภาพสมบูรณ์ ไม่มีฉีกขาด)",
    ]) {
      expect(within(panel).getByText(text)).toBeInTheDocument();
    }
    for (const t of ["Back/Hip/Rib", "Knee", "Shoulder", "Ankle"]) {
      expect(within(panel).getByLabelText(t)).toBeInTheDocument();
      expect(within(panel).getByLabelText(`จำนวน ${t}`)).toBeInTheDocument();
    }
    // each item defaults to ✓
    expect(within(panel).getAllByRole("button", { pressed: true }).filter((b) => b.textContent === "✓")).toHaveLength(6);

    await user.click(within(panel).getByRole("button", { name: "2 สายชาร์จ ×1 ไม่ปกติ" }));
    await user.click(within(panel).getByLabelText("Knee"));
    await user.clear(within(panel).getByLabelText("จำนวน Knee"));
    await user.type(within(panel).getByLabelText("จำนวน Knee"), "2");
    await user.click(within(panel).getByRole("button", { name: "เสร็จ" }));
    expect(screen.getByRole("button", { name: "แก้ไข CRYO1" })).toHaveTextContent("✓✗✓✓✓✓");

    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก (1 เครื่อง)" }));
    await waitFor(() => expect(dispatchBatch).toHaveBeenCalled());
    expect(dispatchBatch.mock.calls[0][0].items[0]).toEqual({
      equipment_id: "c1",
      checks: {
        kind: "cryo_cuff", body_ok: true, charger_ok: false, lid_with_charger_ok: true,
        lid_without_charger_ok: true, hose_oring_ok: true, cuff_ok: true,
        cuffs: { back_hip_rib: 0, knee: 2, shoulder: 0, ankle: 0 },
      },
    });
  });
});

describe("submit results", () => {
  it("shows per-item results: clears succeeded, keeps failed with a Thai message and retries only those", async () => {
    dispatchBatch.mockResolvedValueOnce({
      total: 2, succeeded: 1, failed: 1,
      results: [
        { index: 0, ok: true, equipment_id: "e1", transaction_id: "t1", transaction_no: "TX-77", cuffs_outstanding: null, error: null },
        {
          index: 1, ok: false, equipment_id: "e2", transaction_id: null, transaction_no: null, cuffs_outstanding: null,
          error: { code: "EQUIPMENT_NOT_AVAILABLE", message: "x", status: 409 },
        },
      ],
    });
    const user = userEvent.setup();
    renderPage();
    await pickWard(user, "Ward A");
    await addBcm(user, "BCM001");
    await addBcm(user, "BCM002");
    await screen.findByRole("button", { name: "แก้ไข BCM002" });
    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก (2 เครื่อง)" }));

    expect(await screen.findByText("✓ BCM001 (TX-77)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "แก้ไข BCM001" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "แก้ไข BCM002" })).toBeInTheDocument();
    expect(screen.getByText(/BCM002: เครื่องนี้ไม่พร้อมให้เบิก/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก (1 เครื่อง)" }));
    await waitFor(() => expect(dispatchBatch).toHaveBeenCalledTimes(2));
    expect(dispatchBatch.mock.calls[1][0].items.map((i: { equipment_id: string }) => i.equipment_id)).toEqual(["e2"]);
    expect(useUiStore.getState().wardUsage["ward-1"]).toBe(2);
  });

  it("re-checks the status of an item whose warning appeared after the scan", async () => {
    dispatchBatch.mockResolvedValueOnce({
      total: 1, succeeded: 0, failed: 1,
      results: [{
        index: 0, ok: false, equipment_id: "e1", transaction_id: null, transaction_no: null, cuffs_outstanding: null,
        error: { code: "DISPATCH_STATUS_WARNING", message: "w", status: 409, details: { warning: "defective" } },
      }],
    });
    const user = userEvent.setup();
    renderPage();
    await pickWard(user, "Ward A");
    await addBcm(user, "BCM001");
    await screen.findByRole("button", { name: "แก้ไข BCM001" });
    checkFor.e1 = { status: "unavailable_defective", warning: "defective", requires_acknowledgement: true };
    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก (1 เครื่อง)" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "แก้ไข BCM001" })).toHaveTextContent("⚠ เสีย"));
    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก (1 เครื่อง)" }));
    await waitFor(() => expect(dispatchBatch).toHaveBeenCalledTimes(2));
    expect(dispatchBatch.mock.calls[1][0].items[0]).toMatchObject({
      acknowledge_status_warning: true, expected_status: "unavailable_defective",
    });
  });

  it("requires a ward before confirming", async () => {
    const user = userEvent.setup();
    renderPage();
    await addBcm(user, "BCM001");
    await screen.findByRole("button", { name: "แก้ไข BCM001" });
    expect(screen.getByRole("button", { name: "ยืนยันการเบิก (1 เครื่อง)" })).toBeDisabled();
  });
});

describe("review fixes", () => {
  it("ignores a second confirm while a submit is in flight (ref guard)", async () => {
    let release: (v: unknown) => void = () => undefined;
    dispatchBatch.mockImplementationOnce(
      () =>
        new Promise((res) => {
          release = res;
        }),
    );
    const user = userEvent.setup();
    renderPage();
    await pickWard(user, "Ward A");
    await addBcm(user, "BCM001");
    await screen.findByRole("button", { name: "แก้ไข BCM001" });
    const btn = screen.getByRole("button", { name: "ยืนยันการเบิก (1 เครื่อง)" });
    await user.dblClick(btn);
    expect(dispatchBatch).toHaveBeenCalledTimes(1);
    release({ total: 1, succeeded: 1, failed: 0, results: [{ index: 0, ok: true, equipment_id: "e1", transaction_id: "t", transaction_no: "TX-1", cuffs_outstanding: null, error: null }] });
    expect(await screen.findByText("✓ BCM001 (TX-1)")).toBeInTheDocument();
  });

  it("removes an item with the red notice when the re-check finds it decommissioned", async () => {
    dispatchBatch.mockResolvedValueOnce({
      total: 1, succeeded: 0, failed: 1,
      results: [{ index: 0, ok: false, equipment_id: "e1", transaction_id: null, transaction_no: null, cuffs_outstanding: null, error: { code: "EQUIPMENT_NOT_AVAILABLE", message: "x", status: 409 } }],
    });
    const user = userEvent.setup();
    renderPage();
    await pickWard(user, "Ward A");
    await addBcm(user, "BCM001");
    await screen.findByRole("button", { name: "แก้ไข BCM001" });
    // status changed between scan and submit: the backend now reports a warning, the re-check says decommissioned
    dispatchBatch.mockReset();
    dispatchBatch.mockResolvedValueOnce({
      total: 1, succeeded: 0, failed: 1,
      results: [{ index: 0, ok: false, equipment_id: "e1", transaction_id: null, transaction_no: null, cuffs_outstanding: null, error: { code: "DISPATCH_WARNING_STALE", message: "x", status: 409 } }],
    });
    checkFor.e1 = { status: "decommissioned", warning: "decommissioned", dispatchable: false };
    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก (1 เครื่อง)" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "แก้ไข BCM001" })).not.toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent("⛔ BCM001 ปลดระวางแล้ว ไม่ถูกเพิ่ม");
  });
});
