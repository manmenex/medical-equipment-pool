import "fake-indexeddb/auto";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { IDBFactory } from "fake-indexeddb";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { closeOfflineDb, listOutbox, replaceRefs, setMeta } from "@/offline/offlineStore";
import { recordServerTime, resetServerTimeState } from "@/offline/serverTime";
import { resetStaleAcknowledgement } from "@/offline/staleness";
import { BorrowPage } from "@/pages/BorrowPage";
import { ReturnPage } from "@/pages/ReturnPage";
import { setMarkedOffline } from "@/services/connectivity";
import { useAuthStore } from "@/store/authStore";
import { useUiStore } from "@/store/uiStore";

const requestSync = vi.fn();
vi.mock("@/offline/syncWorker", () => ({ requestSync: () => requestSync() }));

const dispatchBatch = vi.fn();
const receiptBatch = vi.fn();
const listActiveBorrows = vi.fn();
const getEquipment = vi.fn();
const getDispatchCheck = vi.fn();
const searchBcmSuggestions = vi.fn();
const listWards = vi.fn();
const listDepartments = vi.fn();
vi.mock("@/services/borrow", () => ({
  dispatchBatch: (...a: unknown[]) => dispatchBatch(...a),
  receiptBatch: (...a: unknown[]) => receiptBatch(...a),
  listActiveBorrows: (...a: unknown[]) => listActiveBorrows(...a),
}));
vi.mock("@/services/equipment", () => ({
  getEquipment: (...a: unknown[]) => getEquipment(...a),
  resolveEquipmentByQr: vi.fn(),
  getDispatchCheck: (...a: unknown[]) => getDispatchCheck(...a),
  searchBcmSuggestions: (...a: unknown[]) => searchBcmSuggestions(...a),
}));
vi.mock("@/services/masterData", () => ({
  listWards: (...a: unknown[]) => listWards(...a),
  listDepartments: (...a: unknown[]) => listDepartments(...a),
}));
vi.mock("@/components/QRScanner", () => ({ QRScanner: () => <div data-testid="qr-scanner" /> }));
vi.mock("@/hooks/useAuth", async (orig) => ({
  ...(await orig<typeof import("@/hooks/useAuth")>()),
  useAuth: () => ({ user: { id: "u1", role: "equipment_pool_staff" }, isAuthenticated: true, isLoading: false }),
}));

async function seed(snapshotAgeMs = 60_000) {
  await replaceRefs("ref_equipment", [
    { id: "e1", bcm_code: "BCM001", equipment_name: "Infusion Pump", status: "available_at_pool" },
    { id: "e3", bcm_code: "BCM777", equipment_name: "Ventilator", status: "issued_to_ward" },
  ]);
  await replaceRefs("ref_wards", [
    { id: "w1", code: "W1", name: "Ward A", department_id: "d1", phone: null },
    { id: "w2", code: "W2", name: "Ward B", department_id: null, phone: "0222" },
  ]);
  await replaceRefs("ref_departments", [{ id: "d1", code: "D1", name: "Dept", phone: "0111" }]);
  await replaceRefs("ref_open_tx", [{ id: "t3", equipment_id: "e3", ward_id: "w2", borrowed_at: "2026-10-13T01:00:00Z" }]);
  await setMeta("last_snapshot_at", Date.now() - snapshotAgeMs);
  await recordServerTime(Date.now(), Date.now(), { force: true });
}

function renderPage(ui: React.ReactElement, entry = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
  resetServerTimeState();
  resetStaleAcknowledgement();
  vi.clearAllMocks();
  useUiStore.setState({ lastWard: null, wardUsage: {} });
  useAuthStore.setState({ accessToken: "t", user: { id: "u1" } as never });
  listWards.mockResolvedValue([]);
  listDepartments.mockResolvedValue([]);
});
afterEach(async () => {
  setMarkedOffline(false);
  await closeOfflineDb();
  useAuthStore.setState({ accessToken: null, user: null });
});

async function pickWard(user: ReturnType<typeof userEvent.setup>, query: string) {
  await user.type(await screen.findByLabelText("ค้นหาหอผู้ป่วย"), query);
  await user.click(within(await screen.findByRole("listbox")).getByRole("button"));
}
const addBcm = (user: ReturnType<typeof userEvent.setup>, bcm: string) =>
  user.type(screen.getByLabelText("รหัส BCM"), `${bcm}{Enter}`);

describe("offline dispatch (Roadmap PR27/PR28)", () => {
  it("adds from the cache with an offline note, then queues one single dispatch op per item with contact name and checks", async () => {
    await seed();
    await replaceRefs("ref_equipment", [
      { id: "e1", bcm_code: "BCM001", equipment_name: "Infusion Pump", status: "available_at_pool" },
      { id: "e2", bcm_code: "BCM002", equipment_name: "Ventilator", status: "available_at_pool" },
    ]);
    setMarkedOffline(true);
    const user = userEvent.setup();
    renderPage(<BorrowPage />, "/borrow");

    expect(screen.queryByRole("button", { name: "สแกน QR" })).not.toBeInTheDocument(); // QR is online only
    await pickWard(user, "Ward B");
    await waitFor(() => expect(screen.getByLabelText("เบอร์โทร")).toHaveValue("0222"));
    await user.type(screen.getByLabelText("ชื่อผู้รับ"), "คุณสมศรี");
    await addBcm(user, "BCM001");
    await addBcm(user, "BCM002");
    expect(await screen.findByRole("button", { name: "แก้ไข BCM002" })).toBeInTheDocument();
    expect(screen.getAllByText("ตรวจสอบสถานะไม่ได้ (ออฟไลน์)")).toHaveLength(2);
    expect(getDispatchCheck).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก (2 เครื่อง)" }));
    expect(await screen.findByText(/บันทึกในเครื่องแล้ว 2 เครื่อง — รอส่งเมื่อออนไลน์/)).toBeInTheDocument();
    expect(dispatchBatch).not.toHaveBeenCalled();
    expect(searchBcmSuggestions).not.toHaveBeenCalled();
    const recs = await listOutbox("u1");
    expect(recs).toHaveLength(2);
    for (const rec of recs) {
      expect(rec.envelope).toMatchObject({
        user_id: "u1",
        op_type: "dispatch",
        dispatch: {
          ward_id: "w2",
          phone_number: "0222",
          ward_contact_name: "คุณสมศรี",
          dispatch_checks: { kind: "standard", screen_ok: true, charger_ok: true, clamp_ok: true },
        },
      });
    }
    expect(recs.map((r) => (r.envelope as unknown as { dispatch: { equipment_id: string } }).dispatch.equipment_id).sort()).toEqual(["e1", "e2"]);
    expect(requestSync).toHaveBeenCalledTimes(2);
  });

  it("queues an entered HN encrypted on the outbox row only (never in the envelope or in clear), PR29", async () => {
    await seed();
    setMarkedOffline(true);
    const user = userEvent.setup();
    renderPage(<BorrowPage />, "/borrow");
    await pickWard(user, "Ward B");
    await addBcm(user, "BCM001");
    await user.click(await screen.findByRole("button", { name: "แก้ไข BCM001" }));
    await user.type(screen.getByLabelText("HN ผู้ป่วย (ไม่บังคับ)"), "HN-OFF-77");
    await user.click(screen.getByRole("button", { name: "เสร็จ" }));
    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก (1 เครื่อง)" }));
    await screen.findByText(/บันทึกในเครื่องแล้ว 1 เครื่อง/);
    const [rec] = await listOutbox("u1");
    expect(rec.hn_enc).toBeDefined();
    expect(JSON.stringify(rec.envelope)).not.toContain("HN-OFF-77");
    expect(JSON.stringify(rec)).not.toContain("HN-OFF-77");
  });

  it("keeps an item that cannot be queued (already dispatched locally) with the generic message", async () => {
    await seed();
    setMarkedOffline(true);
    const user = userEvent.setup();
    renderPage(<BorrowPage />, "/borrow");
    await pickWard(user, "Ward B");
    await addBcm(user, "BCM001");
    await screen.findByRole("button", { name: "แก้ไข BCM001" });
    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก (1 เครื่อง)" }));
    await screen.findByText(/บันทึกในเครื่องแล้ว 1 เครื่อง/);

    await addBcm(user, "BCM001");
    await screen.findByRole("button", { name: "แก้ไข BCM001" });
    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก (1 เครื่อง)" }));
    expect(await screen.findByText(/ไม่สามารถบันทึกซ้ำได้|ไม่พร้อมให้เบิก/)).toBeInTheDocument();
    expect(await listOutbox("u1")).toHaveLength(1);
  });

  it("shows the full-screen staleness warning; acknowledging leaves a banner and the op is flagged locally", async () => {
    await seed(5 * 3_600_000);
    setMarkedOffline(true);
    const user = userEvent.setup();
    renderPage(<BorrowPage />, "/borrow");

    expect(await screen.findByRole("alertdialog")).toHaveTextContent(/ไม่ได้ซิงค์มานานกว่า 4 ชั่วโมง/);
    await user.click(screen.getByRole("button", { name: "รับทราบและดำเนินการต่อ" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/ไม่ได้ซิงค์/);

    await pickWard(user, "Ward B");
    await addBcm(user, "BCM001");
    await screen.findByRole("button", { name: "แก้ไข BCM001" });
    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก (1 เครื่อง)" }));
    await screen.findByText(/บันทึกในเครื่องแล้ว/);
    expect((await listOutbox("u1"))[0].stale_context).toBe(true);
  });
});

describe("offline receipt (Roadmap PR27/PR28)", () => {
  it("finds the open transaction in the snapshot and queues a receipt op addressed by transaction_id with the new fields", async () => {
    await seed();
    setMarkedOffline(true);
    const user = userEvent.setup();
    renderPage(<ReturnPage />, "/return");

    await user.type(await screen.findByLabelText("ชื่อผู้ส่งคืน"), "คุณมาลี");
    await addBcm(user, "BCM777");
    await user.click(await screen.findByRole("button", { name: "แก้ไข BCM777" }));
    await user.click(screen.getByRole("button", { name: "เสีย" }));
    await user.click(screen.getByRole("button", { name: "เสร็จ" }));
    await user.click(screen.getByRole("button", { name: "ยืนยันการรับคืน (1 เครื่อง)" }));

    expect(await screen.findByText(/บันทึกในเครื่องแล้ว 1 เครื่อง/)).toBeInTheDocument();
    expect(receiptBatch).not.toHaveBeenCalled();
    expect(listActiveBorrows).not.toHaveBeenCalled();
    const [rec] = await listOutbox("u1");
    expect(rec.envelope).toMatchObject({
      user_id: "u1",
      op_type: "receipt",
      receipt: {
        transaction_id: "t3",
        receipt_outcome: "defective",
        ward_contact_name: "คุณมาลี",
        receipt_checks: { kind: "standard", screen_ok: true, charger_ok: true, clamp_ok: true },
      },
    });
    expect(requestSync).toHaveBeenCalledTimes(1);
  });

  it("includes this user's own offline dispatch as a receivable transaction", async () => {
    await seed();
    setMarkedOffline(true);
    const user = userEvent.setup();
    const { unmount } = renderPage(<BorrowPage />, "/borrow");
    await pickWard(user, "Ward B");
    await addBcm(user, "BCM001");
    await screen.findByRole("button", { name: "แก้ไข BCM001" });
    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก (1 เครื่อง)" }));
    await screen.findByText(/บันทึกในเครื่องแล้ว/);
    unmount();

    renderPage(<ReturnPage />, "/return");
    await addBcm(user, "BCM001");
    expect(await screen.findByRole("button", { name: "แก้ไข BCM001" })).toBeInTheDocument();
  });

  it("offers the dispatch switch (D28) for equipment at the pool with no open transaction", async () => {
    await seed();
    setMarkedOffline(true);
    const user = userEvent.setup();
    renderPage(<ReturnPage />, "/return");
    await addBcm(user, "BCM001");
    expect(await screen.findByRole("alert")).toHaveTextContent("เครื่องนี้อยู่ในคลัง — จ่ายแทน?");
  });
});

describe("online path", () => {
  it("dispatch uses dispatch-batch and writes nothing to the outbox", async () => {
    await seed();
    getEquipment.mockResolvedValue({
      id: "e1", asset_number: "AST-1", serial_number: null, equipment_name: "Infusion Pump", category_id: null,
      brand: null, model: null, department_owner_id: null, current_location_id: null, status: "available_at_pool",
      bcm_code: "BCM001", pm_due_date: null, cal_due_date: null, created_at: "", updated_at: "",
    });
    getDispatchCheck.mockResolvedValue({
      equipment_id: "e1", status: "available_at_pool", warning: null, dispatchable: true, requires_acknowledgement: false,
      current_ward_id: null, current_ward_name: null, dispatched_at: null, open_transaction_id: null,
      open_transaction_no: null, checklist_kind: "standard",
    });
    listWards.mockResolvedValue([{ id: "w1", code: "W1", name: "Ward A", department_id: null }]);
    dispatchBatch.mockResolvedValue({
      total: 1, succeeded: 1, failed: 0,
      results: [{ index: 0, ok: true, equipment_id: "e1", transaction_id: "t", transaction_no: "TX-9", cuffs_outstanding: null, error: null }],
    });
    const user = userEvent.setup();
    renderPage(<BorrowPage />, "/borrow?equipment_id=e1");

    await screen.findByRole("button", { name: "แก้ไข BCM001" });
    await pickWard(user, "Ward A");
    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก (1 เครื่อง)" }));

    expect(await screen.findByText("✓ BCM001 (TX-9)")).toBeInTheDocument();
    expect(dispatchBatch).toHaveBeenCalledTimes(1);
    expect(await listOutbox("u1")).toEqual([]);
    expect(requestSync).not.toHaveBeenCalled();
  });

  it("receipt shows the QR button", async () => {
    await seed();
    renderPage(<ReturnPage />, "/return");
    expect(screen.getByRole("button", { name: "สแกน QR" })).toBeInTheDocument();
  });
});

describe("offline Cryo-Cuff (Roadmap PR28)", () => {
  it("receipt: uses the cached kind and issued cuffs; the queued op carries cryo checks and the cuffs returned", async () => {
    await seed();
    await replaceRefs("ref_equipment", [
      { id: "c1", bcm_code: "CRYO1", equipment_name: "Cryo", category_name: "Cryo-Cuff", checklist_kind: "cryo_cuff", status: "issued_to_ward" },
    ]);
    await replaceRefs("ref_open_tx", [
      { id: "tc", equipment_id: "c1", ward_id: "w2", borrowed_at: "2026-10-13T01:00:00Z", checklist_kind: "cryo_cuff", cuffs_issued: { back_hip_rib: 0, knee: 2, shoulder: 0, ankle: 1 } },
    ]);
    setMarkedOffline(true);
    const user = userEvent.setup();
    renderPage(<ReturnPage />, "/return");
    await addBcm(user, "CRYO1");
    await user.click(await screen.findByRole("button", { name: "แก้ไข CRYO1" }));
    expect(within(screen.getByRole("group", { name: "แก้ไข CRYO1" })).getAllByRole("listitem")).toHaveLength(6);
    expect(screen.getByLabelText("จำนวน Knee")).toHaveValue(2);
    await user.click(screen.getByRole("button", { name: "เสร็จ" }));
    await user.click(screen.getByRole("button", { name: "ยืนยันการรับคืน (1 เครื่อง)" }));
    await screen.findByText(/บันทึกในเครื่องแล้ว 1 เครื่อง/);
    const [rec] = await listOutbox("u1");
    expect(rec.envelope).toMatchObject({
      receipt: {
        transaction_id: "tc",
        receipt_checks: { kind: "cryo_cuff", cuffs: { back_hip_rib: 0, knee: 2, shoulder: 0, ankle: 1 } },
        cuffs_returned: { back_hip_rib: 0, knee: 2, shoulder: 0, ankle: 1 },
      },
    });
  });

  it("dispatch: an old cache without checklist_kind falls back to the category name (cryo)", async () => {
    await seed();
    await replaceRefs("ref_equipment", [
      { id: "c1", bcm_code: "CRYO1", equipment_name: "Cryo", category_name: "CRYO CUFF", status: "available_at_pool" },
    ]);
    setMarkedOffline(true);
    const user = userEvent.setup();
    renderPage(<BorrowPage />, "/borrow");
    await pickWard(user, "Ward B");
    await addBcm(user, "CRYO1");
    await user.click(await screen.findByRole("button", { name: "แก้ไข CRYO1" }));
    expect(within(screen.getByRole("group", { name: "แก้ไข CRYO1" })).getAllByRole("listitem")).toHaveLength(6);
    await user.click(screen.getByRole("button", { name: "เสร็จ" }));
    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก (1 เครื่อง)" }));
    await screen.findByText(/บันทึกในเครื่องแล้ว 1 เครื่อง/);
    const [rec] = await listOutbox("u1");
    expect(rec.envelope).toMatchObject({ dispatch: { dispatch_checks: { kind: "cryo_cuff" } } });
  });
});
