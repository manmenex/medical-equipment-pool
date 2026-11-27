import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
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
const undoTransaction = vi.fn();

vi.mock("@/services/equipment", () => ({
  getEquipment: (...a: unknown[]) => getEquipment(...a),
  resolveEquipmentByQr: (...a: unknown[]) => resolveEquipmentByQr(...a),
  searchBcmSuggestions: (...a: unknown[]) => searchBcmSuggestions(...a),
  getDispatchCheck: (...a: unknown[]) => getDispatchCheck(...a),
}));
vi.mock("@/services/borrow", () => ({
  dispatchBatch: (...a: unknown[]) => dispatchBatch(...a),
  undoTransaction: (...a: unknown[]) => undoTransaction(...a),
}));
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


function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="loc">{loc.pathname + loc.search}</div>;
}

function renderPage(entry = "/borrow") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}>
        <LocationProbe />
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
  it("shows the 3 sections, shift chip, note input and no HN text until an item is open", async () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "หอผู้ป่วย" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "สแกนเครื่อง (0 เครื่อง)" })).toBeInTheDocument();
    expect(screen.getByTestId("shift-chip")).toHaveTextContent(/^(Day|Night) · \d{2}:\d{2}$/);
    expect(screen.getByLabelText("ชื่อผู้รับ")).toBeInTheDocument();
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
    expect(screen.getByRole("group", { name: "แก้ไข BCM001" })).toHaveTextContent(/ถูกจ่ายไป Ward Z ยังไม่รับคืน/);
  });
});

describe("edit panel and checks", () => {
  it("opens an inline panel with 3 default-checked boxes; unchecking one is sent and shown as ✗; done closes it", async () => {
    const user = userEvent.setup();
    renderPage();
    await pickWard(user, "Ward A");
    await user.type(screen.getByLabelText("ชื่อผู้รับ"), "คุณสมศรี");
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

describe("patient HN (Roadmap PR29, D1)", () => {
  it("is optional: an item without HN shows no 🔒HN and sends no hn key", async () => {
    const user = userEvent.setup();
    renderPage();
    await pickWard(user, "Ward A");
    await addBcm(user, "BCM001");
    expect(await screen.findByRole("button", { name: "แก้ไข BCM001" })).not.toHaveTextContent("🔒HN");
    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก (1 เครื่อง)" }));
    await waitFor(() => expect(dispatchBatch).toHaveBeenCalled());
    expect(dispatchBatch.mock.calls[0][0].items[0]).not.toHaveProperty("hn");
  });

  it("puts the HN field in the edit panel; entered HN is masked, the row shows 🔒HN, and it is sent per item", async () => {
    const user = userEvent.setup();
    renderPage();
    await pickWard(user, "Ward A");
    await addBcm(user, "BCM001");
    await addBcm(user, "BCM002");
    await user.click(await screen.findByRole("button", { name: "แก้ไข BCM001" }));
    const panel = screen.getByRole("group", { name: "แก้ไข BCM001" });
    await user.type(within(panel).getByLabelText("HN ผู้ป่วย (ไม่บังคับ)"), "AB-123/9");
    await user.click(within(panel).getByRole("button", { name: "เสร็จ" })); // leaves the field -> masked
    expect(screen.getByRole("button", { name: "แก้ไข BCM001" })).toHaveTextContent("🔒HN");
    expect(screen.getByRole("button", { name: "แก้ไข BCM002" })).not.toHaveTextContent("🔒HN");
    // The value is never in the row text.
    expect(document.body.textContent).not.toContain("AB-123/9");

    // Re-open: masked with แสดง HN; the local value is revealed on click.
    await user.click(screen.getByRole("button", { name: "แก้ไข BCM001" }));
    const again = screen.getByRole("group", { name: "แก้ไข BCM001" });
    expect(within(again).getByTestId("hn-masked")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("AB-123/9");
    await user.click(within(again).getByRole("button", { name: "แสดง HN" }));
    expect(within(again).getByTestId("hn-value")).toHaveTextContent("AB-123/9");
    await user.click(within(again).getByRole("button", { name: "เสร็จ" }));

    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก (2 เครื่อง)" }));
    await waitFor(() => expect(dispatchBatch).toHaveBeenCalled());
    const items = dispatchBatch.mock.calls[0][0].items;
    expect(items[0]).toMatchObject({ equipment_id: "e1", hn: "AB-123/9" });
    expect(items[1]).not.toHaveProperty("hn");
    expect(JSON.stringify({ ...localStorage })).not.toContain("AB-123/9");
  });

  it("ignores characters the server would reject and clears back to no indicator", async () => {
    const user = userEvent.setup();
    renderPage();
    await addBcm(user, "BCM001");
    await user.click(await screen.findByRole("button", { name: "แก้ไข BCM001" }));
    const input = screen.getByLabelText("HN ผู้ป่วย (ไม่บังคับ)");
    await user.type(input, "12 3;4");
    expect(input).toHaveValue("1234");
    await user.clear(input);
    await user.click(screen.getByRole("button", { name: "เสร็จ" }));
    expect(screen.getByRole("button", { name: "แก้ไข BCM001" })).not.toHaveTextContent("🔒HN");
  });
});

// Roadmap PR33 (D14): demo/loan badges on scan rows; a device returned to its owner is not added.
describe("demo/loan devices (PR33)", () => {
  it("shows the DEMO badge on the scan row for a demo device", async () => {
    EQ.SNDEMO1 = { ...equipment("d1", "SNDEMO1", "Demo Pump"), equipment_source: "demo" };
    const user = userEvent.setup();
    renderPage();
    await addBcm(user, "SNDEMO1");
    const row = await screen.findByRole("button", { name: "แก้ไข SNDEMO1" });
    expect(within(row).getByTestId("source-badge")).toHaveTextContent("DEMO");
    delete EQ.SNDEMO1;
  });

  it("shows ยืม for a loaned device and no badge for a pool device", async () => {
    EQ.SNLOAN1 = { ...equipment("l1", "SNLOAN1", "Loan Pump"), equipment_source: "loan" };
    const user = userEvent.setup();
    renderPage();
    await addBcm(user, "SNLOAN1");
    await addBcm(user, "BCM001");
    const loanRow = await screen.findByRole("button", { name: "แก้ไข SNLOAN1" });
    expect(within(loanRow).getByTestId("source-badge")).toHaveTextContent("ยืม");
    const poolRow = await screen.findByRole("button", { name: "แก้ไข BCM001" });
    expect(within(poolRow).queryByTestId("source-badge")).not.toBeInTheDocument();
    delete EQ.SNLOAN1;
  });

  it("does not add a device returned to its owner", async () => {
    EQ.SNRET1 = { ...equipment("r1", "SNRET1", "Returned Pump"), equipment_source: "loan" };
    checkFor.r1 = { warning: "returned_to_owner", dispatchable: false };
    const user = userEvent.setup();
    renderPage();
    await addBcm(user, "SNRET1");
    expect(await screen.findByRole("alert")).toHaveTextContent("คืนผู้ให้ยืมแล้ว");
    expect(screen.queryByRole("button", { name: "แก้ไข SNRET1" })).not.toBeInTheDocument();
    delete EQ.SNRET1;
  });
});

describe("D28 prevention and undo (dispatch)", () => {
  it("offers a one-tap switch to receipt when the device is still out at a ward", async () => {
    checkFor.e1 = { status: "issued_to_ward", warning: "already_dispatched", current_ward_name: "Ward Z", open_transaction_id: "tx-open" };
    const user = userEvent.setup();
    renderPage();
    await addBcm(user, "BCM001");
    expect(await screen.findByText("เครื่องนี้อยู่ที่ Ward Z — รับคืนแทน?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "รับคืนแทน" }));
    expect(screen.getByTestId("loc")).toHaveTextContent("/return?equipment_id=e1");
  });

  it("does not show the switch prompt for an available device", async () => {
    const user = userEvent.setup();
    renderPage();
    await addBcm(user, "BCM001");
    await screen.findByRole("button", { name: "แก้ไข BCM001" });
    expect(screen.queryByText(/รับคืนแทน/)).not.toBeInTheDocument();
  });

  it("flags a device scanned twice and does not add it twice", async () => {
    const user = userEvent.setup();
    renderPage();
    await addBcm(user, "BCM001");
    await screen.findByRole("button", { name: "แก้ไข BCM001" });
    await addBcm(user, "BCM001");
    expect(await screen.findByRole("alert")).toHaveTextContent("BCM001 สแกนซ้ำ");
    expect(screen.getByRole("heading", { name: "สแกนเครื่อง (1 เครื่อง)" })).toBeInTheDocument();
  });

  it("shows the undo toast with a 2:00 countdown and undoes every saved transaction", async () => {
    undoTransaction.mockResolvedValue({ transaction: {}, new_transaction: null });
    const user = userEvent.setup();
    renderPage();
    await pickWard(user, "Ward A");
    await addBcm(user, "BCM001");
    await addBcm(user, "BCM002");
    await screen.findByRole("button", { name: "แก้ไข BCM002" });
    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก (2 เครื่อง)" }));
    const toast = await screen.findByRole("button", { name: "บันทึกแล้ว · เลิกทำ (2:00)" });
    await user.click(toast);
    await waitFor(() => expect(undoTransaction).toHaveBeenCalledTimes(2));
    expect(undoTransaction.mock.calls.map((c) => c[0])).toEqual(["t0", "t1"]);
    expect(await screen.findByText("เลิกทำแล้ว 2 รายการ")).toBeInTheDocument();
  });
});
