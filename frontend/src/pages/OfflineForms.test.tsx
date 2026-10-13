import "fake-indexeddb/auto";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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

const createBorrow = vi.fn();
const createReturn = vi.fn();
const listActiveBorrows = vi.fn();
const getEquipment = vi.fn();
const searchBcmSuggestions = vi.fn();
const listWards = vi.fn();
const listDepartments = vi.fn();
vi.mock("@/services/borrow", () => ({
  createBorrow: (...a: unknown[]) => createBorrow(...a),
  createReturn: (...a: unknown[]) => createReturn(...a),
  listActiveBorrows: (...a: unknown[]) => listActiveBorrows(...a),
}));
vi.mock("@/services/equipment", () => ({
  getEquipment: (...a: unknown[]) => getEquipment(...a),
  resolveEquipmentByQr: vi.fn(),
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
  useUiStore.setState({ lastWard: null });
  useAuthStore.setState({ accessToken: "t", user: { id: "u1" } as never });
  listWards.mockResolvedValue([]);
  listDepartments.mockResolvedValue([]);
});
afterEach(async () => {
  setMarkedOffline(false);
  await closeOfflineDb();
  useAuthStore.setState({ accessToken: null, user: null });
});

describe("offline dispatch form", () => {
  it("searches the cache by BCM, prefills the phone from cached ward/department, enqueues, shows pending state", async () => {
    await seed();
    setMarkedOffline(true);
    const user = userEvent.setup();
    renderPage(<BorrowPage />, "/borrow");

    expect(screen.queryByTestId("qr-scanner")).not.toBeInTheDocument(); // QR is online only
    expect(screen.getByText(/สแกน QR ใช้ได้เฉพาะตอนออนไลน์/)).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText("กรอกรหัส BCM"), "001");
    await user.click(await screen.findByRole("button", { name: "BCM001" }));
    await screen.findByText("Infusion Pump");

    await user.selectOptions(await screen.findByLabelText(/หอผู้ป่วยที่รับเครื่อง/), "w1");
    // ward has no phone -> department fallback from the cached snapshot
    await waitFor(() => expect(screen.getByLabelText("เบอร์โทร")).toHaveValue("0111"));
    await user.selectOptions(screen.getByLabelText(/หอผู้ป่วยที่รับเครื่อง/), "w2");
    // operator has not typed their own value yet -> ward phone refills
    await waitFor(() => expect(screen.getByLabelText("เบอร์โทร")).toHaveValue("0222"));

    await user.click(screen.getByRole("button", { name: "บันทึกการเบิก (ในเครื่อง)" }));

    expect(await screen.findByText(/บันทึกในเครื่องแล้ว — ยังไม่ได้ส่งเข้าระบบ/)).toBeInTheDocument();
    expect(screen.queryByText("เบิกสำเร็จ")).not.toBeInTheDocument();
    expect(createBorrow).not.toHaveBeenCalled();
    expect(getEquipment).not.toHaveBeenCalled();
    expect(searchBcmSuggestions).not.toHaveBeenCalled();
    const [rec] = await listOutbox("u1");
    expect(rec.envelope).toMatchObject({
      user_id: "u1",
      op_type: "dispatch",
      dispatch: { equipment_id: "e1", ward_id: "w2", dispatch_type: "on_demand", phone_number: "0222" },
    });
    expect(requestSync).toHaveBeenCalledTimes(1);
  });

  it("blocks a second offline dispatch of the same equipment with the generic message", async () => {
    await seed();
    setMarkedOffline(true);
    const user = userEvent.setup();
    renderPage(<BorrowPage />, "/borrow");
    for (let i = 0; i < 2; i++) {
      await user.type(screen.getByPlaceholderText("กรอกรหัส BCM"), "001");
      await user.click(await screen.findByRole("button", { name: "BCM001" }));
      await screen.findByText("Infusion Pump");
      if (i === 1) break;
      await user.selectOptions(await screen.findByLabelText(/หอผู้ป่วยที่รับเครื่อง/), "w2");
      await user.click(screen.getByRole("button", { name: "บันทึกการเบิก (ในเครื่อง)" }));
      await user.click(await screen.findByRole("button", { name: "เบิกเครื่องถัดไป" }));
    }
    // second time the cache already treats it as dispatched (not yet synced)
    expect(await screen.findByText(/ไม่พร้อมให้เบิก/)).toBeInTheDocument();
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

    await user.type(screen.getByPlaceholderText("กรอกรหัส BCM"), "001");
    await user.click(await screen.findByRole("button", { name: "BCM001" }));
    await user.selectOptions(await screen.findByLabelText(/หอผู้ป่วยที่รับเครื่อง/), "w2");
    await user.click(screen.getByRole("button", { name: "บันทึกการเบิก (ในเครื่อง)" }));
    await screen.findByText(/บันทึกในเครื่องแล้ว/);
    expect((await listOutbox("u1"))[0].stale_context).toBe(true);
  });
});

describe("offline receipt form", () => {
  it("lists cached open transactions plus local dispatches and enqueues a receipt by transaction_id", async () => {
    await seed();
    setMarkedOffline(true);
    const user = userEvent.setup();
    renderPage(<ReturnPage />, "/return");

    expect(screen.queryByTestId("qr-scanner")).not.toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: /BCM777/ }));
    await user.click(screen.getByLabelText("ชำรุด"));
    await user.type(screen.getByLabelText("หมายเหตุ"), "cracked");
    await user.click(screen.getByRole("button", { name: "บันทึกการรับคืน (ในเครื่อง)" }));

    expect(await screen.findByText(/บันทึกในเครื่องแล้ว — ยังไม่ได้ส่งเข้าระบบ/)).toBeInTheDocument();
    expect(createReturn).not.toHaveBeenCalled();
    expect(listActiveBorrows).not.toHaveBeenCalled();
    const [rec] = await listOutbox("u1");
    expect(rec.envelope).toMatchObject({
      user_id: "u1",
      op_type: "receipt",
      receipt: { transaction_id: "t3", receipt_outcome: "defective", notes: "cracked" },
    });
    expect(requestSync).toHaveBeenCalledTimes(1);
    // the received transaction no longer appears in the list
    await user.click(screen.getByRole("button", { name: "รับคืนเครื่องถัดไป" }));
    await screen.findByText(/ไม่พบรายการเบิกที่ค้างอยู่/);
  });

  it("includes this user's own offline dispatch in the receipt list", async () => {
    await seed();
    setMarkedOffline(true);
    const user = userEvent.setup();
    const { unmount } = renderPage(<BorrowPage />, "/borrow");
    await user.type(screen.getByPlaceholderText("กรอกรหัส BCM"), "001");
    await user.click(await screen.findByRole("button", { name: "BCM001" }));
    await user.selectOptions(await screen.findByLabelText(/หอผู้ป่วยที่รับเครื่อง/), "w2");
    await user.click(screen.getByRole("button", { name: "บันทึกการเบิก (ในเครื่อง)" }));
    await screen.findByText(/บันทึกในเครื่องแล้ว/);
    unmount();

    renderPage(<ReturnPage />, "/return");
    expect(await screen.findByRole("button", { name: /BCM001/ })).toHaveTextContent(/เบิกในเครื่องนี้/);
    expect(screen.getByRole("button", { name: /BCM777/ })).toBeInTheDocument();
  });
});

describe("online path unchanged", () => {
  it("dispatch uses POST /borrow via createBorrow and writes nothing to the outbox", async () => {
    await seed();
    getEquipment.mockResolvedValue({
      id: "e1", asset_number: "AST-1", serial_number: null, equipment_name: "Infusion Pump", category_id: null,
      brand: null, model: null, department_owner_id: null, current_location_id: null, status: "available_at_pool",
      bcm_code: "BCM001", pm_due_date: null, cal_due_date: null, created_at: "", updated_at: "",
    });
    listWards.mockResolvedValue([{ id: "w1", code: "W1", name: "Ward A", department_id: null }]);
    createBorrow.mockResolvedValue({ transaction_no: "TX-9" });
    const user = userEvent.setup();
    renderPage(<BorrowPage />, "/borrow?equipment_id=e1");

    await screen.findByText("AST-1");
    await user.selectOptions(await screen.findByLabelText(/หอผู้ป่วยที่รับเครื่อง/), "w1");
    await user.click(screen.getByRole("button", { name: "ยืนยันการเบิก" }));

    expect(await screen.findByText("เบิกสำเร็จ")).toBeInTheDocument();
    expect(createBorrow).toHaveBeenCalledTimes(1);
    expect(await listOutbox("u1")).toEqual([]);
    expect(requestSync).not.toHaveBeenCalled();
  });

  it("receipt shows the QR scanner and never the offline list", async () => {
    await seed();
    renderPage(<ReturnPage />, "/return");
    expect(screen.getByTestId("qr-scanner")).toBeInTheDocument();
    expect(screen.queryByText(/สแกน QR ใช้ได้เฉพาะตอนออนไลน์/)).not.toBeInTheDocument();
  });
});
