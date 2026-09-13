import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReconciliationRunDetailPage } from "@/pages/ReconciliationRunDetailPage";
import type { Equipment, Page, UserProfile } from "@/types";
import type {
  ReconciliationFindingDetail,
  ReconciliationFindingListItem,
  ReconciliationRunDetail,
  ReconciliationSignOffDetail,
} from "@/types/reconciliation";

const fetchReconciliationRun = vi.fn();
const fetchReconciliationSignoff = vi.fn();
const fetchReconciliationFindings = vi.fn();
const fetchReconciliationFinding = vi.fn();
const updateReconciliationFindingDisposition = vi.fn();
const createReconciliationSignoff = vi.fn();

vi.mock("@/services/reconciliation", async () => {
  const actual = await vi.importActual<typeof import("@/services/reconciliation")>("@/services/reconciliation");
  return {
    ...actual,
    fetchReconciliationRun: (...args: unknown[]) => fetchReconciliationRun(...args),
    fetchReconciliationSignoff: (...args: unknown[]) => fetchReconciliationSignoff(...args),
    fetchReconciliationFindings: (...args: unknown[]) => fetchReconciliationFindings(...args),
    fetchReconciliationFinding: (...args: unknown[]) => fetchReconciliationFinding(...args),
    updateReconciliationFindingDisposition: (...args: unknown[]) => updateReconciliationFindingDisposition(...args),
    createReconciliationSignoff: (...args: unknown[]) => createReconciliationSignoff(...args),
  };
});

// Roadmap PR22F Fix Round 1 (P1 #2): the equipment finding-filter reuses
// the existing services/equipment.ts searchEquipment -- mocked here the
// same way components/OperatorAutocomplete.test.tsx mocks its own search
// dependency.
const searchEquipment = vi.fn();
vi.mock("@/services/equipment", async () => {
  const actual = await vi.importActual<typeof import("@/services/equipment")>("@/services/equipment");
  return {
    ...actual,
    searchEquipment: (...args: unknown[]) => searchEquipment(...args),
  };
});

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

function fakeApiError(code: string, detail = "error", status = 409) {
  return { isAxiosError: true, response: { status, data: { code, detail, status } } };
}

function makeRun(overrides: Partial<ReconciliationRunDetail> = {}): ReconciliationRunDetail {
  return {
    id: "run-1",
    status: "completed",
    version: 0,
    rule_version: "pr22-v1",
    snapshot_as_of: "2026-07-01T00:00:00Z",
    created_by_user_id: "user-9",
    created_at: "2026-07-01T00:00:00Z",
    started_at: "2026-07-01T00:00:00Z",
    completed_at: "2026-07-01T00:05:00Z",
    failed_at: null,
    legacy_coverage_start: "2020-01-01T00:00:00Z",
    legacy_coverage_end: "2024-12-31T00:00:00Z",
    live_system_start: "2025-01-01T00:00:00Z",
    summary_total_findings: 1,
    summary_high: 1,
    summary_medium: 0,
    summary_low: 0,
    has_signoff: false,
    coverage_id: "cov-1",
    supersedes_run_id: null,
    finding_counts_by_disposition: { open: 1 },
    ...overrides,
  };
}

function makeFindingListItem(overrides: Partial<ReconciliationFindingListItem> = {}): ReconciliationFindingListItem {
  return {
    id: "finding-1",
    run_id: "run-1",
    code: "DUPLICATE_EXACT",
    severity: "high",
    equipment_id: "equip-1",
    rule_version: "pr22-v1",
    disposition: null,
    disposed_by_user_id: null,
    disposed_at: null,
    disposition_note: null,
    version: 0,
    created_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

function makeFindingDetail(overrides: Partial<ReconciliationFindingDetail> = {}): ReconciliationFindingDetail {
  return {
    ...makeFindingListItem(),
    evidence: { reason_code: "test" },
    equipment: {
      id: "equip-1",
      asset_number: "AN-1",
      equipment_name: "Infusion Pump",
      item_no: null,
      bcm_code: "BCM1",
      status: "available_at_pool",
    },
    events: [],
    ...overrides,
  };
}

function makeSignoff(overrides: Partial<ReconciliationSignOffDetail> = {}): ReconciliationSignOffDetail {
  return {
    id: "signoff-1",
    run_id: "run-1",
    signed_off_by_user_id: "user-9",
    signed_off_at: "2026-07-02T00:00:00Z",
    attestation_summary: { rule_version: "pr22-v1" },
    run_version_at_signoff: 0,
    ...overrides,
  };
}

function findingsPage(items: ReconciliationFindingListItem[]): Page<ReconciliationFindingListItem> {
  return { items, next_cursor: null, total: items.length };
}

function makeEquipment(overrides: Partial<Equipment> = {}): Equipment {
  return {
    id: "equip-9",
    asset_number: "AN-9",
    serial_number: null,
    equipment_name: "Infusion Pump 9",
    category_id: null,
    brand: null,
    model: null,
    department_owner_id: null,
    current_location_id: null,
    status: "available_at_pool",
    bcm_code: "BCM9",
    pm_due_date: null,
    cal_due_date: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  mockUser = makeUser("administrator");
  fetchReconciliationRun.mockResolvedValue(makeRun());
  fetchReconciliationSignoff.mockRejectedValue(fakeApiError("RECONCILIATION_SIGNOFF_NOT_FOUND", "not signed", 404));
  fetchReconciliationFindings.mockResolvedValue(findingsPage([makeFindingListItem()]));
  fetchReconciliationFinding.mockResolvedValue(makeFindingDetail());
  searchEquipment.mockResolvedValue({ items: [], next_cursor: null, total: 0 });
});

afterEach(() => {
  vi.resetAllMocks();
});

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/reconciliation/run-1"]}>
        <Routes>
          <Route path="/reconciliation/:runId" element={<ReconciliationRunDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("ReconciliationRunDetailPage -- read UX", () => {
  it("renders run summary, coverage, and review progress once loaded", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("pr22-v1")).toBeInTheDocument());
    expect(screen.getByText("ประมวลผลเสร็จ")).toBeInTheDocument();
    expect(screen.getByText(/ช่วงเวลาข้อมูลที่ได้รับอนุมัติ/)).toBeInTheDocument();
    expect(screen.getByText(/ความคืบหน้าการตรวจสอบ/)).toBeInTheDocument();
  });

  it("shows an error state with retry if the run fails to load", async () => {
    fetchReconciliationRun.mockRejectedValue(new Error("boom"));
    renderPage();
    await waitFor(() => expect(screen.getByText(/ไม่สามารถโหลดข้อมูลรอบการตรวจสอบได้/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "ลองใหม่" })).toBeInTheDocument();
  });

  it("treats sign-off 404 as the normal unsigned state, not a red error panel", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("รอบการตรวจสอบนี้ยังไม่ได้ลงนามยืนยัน")).toBeInTheDocument());
    expect(screen.queryByText(/ไม่สามารถตรวจสอบสถานะการลงนามได้/)).not.toBeInTheDocument();
  });

  it("shows the signed-off attestation card when a sign-off exists", async () => {
    fetchReconciliationSignoff.mockResolvedValue(makeSignoff());
    renderPage();
    await waitFor(() => expect(screen.getAllByText("ลงนามยืนยันแล้ว").length).toBeGreaterThan(0));
    expect(screen.queryByText("รอบการตรวจสอบนี้ยังไม่ได้ลงนามยืนยัน")).not.toBeInTheDocument();
  });

  it("shows empty state when no findings match filters", async () => {
    fetchReconciliationFindings.mockResolvedValue(findingsPage([]));
    renderPage();
    await waitFor(() => expect(screen.getByText("ไม่พบรายการตามตัวกรองที่เลือก")).toBeInTheDocument());
  });
});

describe("ReconciliationRunDetailPage -- role-aware usability gating", () => {
  it("administrator sees disposition and sign-off actions", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByText("ลงนามยืนยันผลการตรวจสอบ")).toBeInTheDocument());
    await user.click(findingCardButton());
    expect(await screen.findByRole("button", { name: "บันทึกผลการตรวจสอบ" })).toBeInTheDocument();
  });

  it("equipment_pool_staff sees read page but no mutation actions", async () => {
    mockUser = makeUser("equipment_pool_staff");
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByText("รอบการตรวจสอบนี้ยังไม่ได้ลงนามยืนยัน")).toBeInTheDocument());
    expect(screen.queryByText("ลงนามยืนยันผลการตรวจสอบ")).not.toBeInTheDocument();
    await user.click(findingCardButton());
    await waitFor(() => expect(fetchReconciliationFinding).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "บันทึกผลการตรวจสอบ" })).not.toBeInTheDocument();
  });

  it("read_only sees read page but no mutation actions", async () => {
    mockUser = makeUser("read_only");
    renderPage();
    await waitFor(() => expect(screen.getByText("รอบการตรวจสอบนี้ยังไม่ได้ลงนามยืนยัน")).toBeInTheDocument());
    expect(screen.queryByText("ลงนามยืนยันผลการตรวจสอบ")).not.toBeInTheDocument();
  });
});

function reconciliationFindingLabel() {
  return "ข้อมูลซ้ำซ้อนทั้งหมด";
}

// Roadmap PR22F Fix Round 1: the same Thai label also appears as an
// <option> in the new finding-code filter <select> (both render from the
// same RECONCILIATION_FINDING_CODE_LABELS map), so a plain getByText()
// now matches two elements. Scope to the finding card's own button role,
// whose accessible name is a superset containing this label, so clicking
// it stays unambiguous.
function findingCardButton() {
  return screen.getByRole("button", { name: new RegExp(reconciliationFindingLabel()) });
}

function findFindingCardButton() {
  return screen.findByRole("button", { name: new RegExp(reconciliationFindingLabel()) });
}

describe("ReconciliationRunDetailPage -- disposition", () => {
  beforeEach(() => {
    fetchReconciliationFinding.mockResolvedValue(makeFindingDetail());
  });

  it("renders all four disposition options and never confirmed_pair", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(findingCardButton()).toBeInTheDocument());
    await user.click(findingCardButton());
    await user.click(await screen.findByRole("button", { name: "บันทึกผลการตรวจสอบ" }));

    const dialog = await screen.findByRole("dialog", { name: "บันทึกผลการตรวจสอบรายการ" });
    const radios = within(dialog).getAllByRole("radio");
    expect(radios).toHaveLength(4);
    expect(within(dialog).queryByText(/confirmed_pair/)).not.toBeInTheDocument();
    expect(within(dialog).getByText("ยืนยันว่าข้อมูลถูกต้อง")).toBeInTheDocument();
    expect(within(dialog).getByText("ยืนยันว่าเป็นข้อมูลซ้ำ")).toBeInTheDocument();
    expect(within(dialog).getByText("ยอมรับว่ายังไม่สามารถแก้ไขได้")).toBeInTheDocument();
    expect(within(dialog).getByText("ต้องดำเนินการแก้ไข")).toBeInTheDocument();
  });

  it("submits the finding's exact currently-loaded version, refetches on success", async () => {
    updateReconciliationFindingDisposition.mockResolvedValue(makeFindingDetail({ disposition: "confirmed_valid", version: 1 }));
    const user = userEvent.setup();
    renderPage();
    await user.click(await findFindingCardButton());
    await user.click(await screen.findByRole("button", { name: "บันทึกผลการตรวจสอบ" }));
    const dialog = await screen.findByRole("dialog", { name: "บันทึกผลการตรวจสอบรายการ" });
    await user.click(within(dialog).getByLabelText("ยืนยันว่าข้อมูลถูกต้อง"));
    await user.click(within(dialog).getByRole("button", { name: "ยืนยันผลการตรวจสอบรายการนี้" }));

    await waitFor(() =>
      expect(updateReconciliationFindingDisposition).toHaveBeenCalledWith("finding-1", {
        disposition: "confirmed_valid",
        expected_version: 0,
        disposition_note: null,
      })
    );
    await waitFor(() => expect(screen.getByText("บันทึกผลการตรวจสอบสำเร็จ")).toBeInTheDocument());
  });

  it("on VERSION_CONFLICT shows the conflict message and does not auto-retry", async () => {
    updateReconciliationFindingDisposition.mockRejectedValue(fakeApiError("RECONCILIATION_FINDING_VERSION_CONFLICT"));
    const user = userEvent.setup();
    renderPage();
    await user.click(await findFindingCardButton());
    await user.click(await screen.findByRole("button", { name: "บันทึกผลการตรวจสอบ" }));
    const dialog = await screen.findByRole("dialog", { name: "บันทึกผลการตรวจสอบรายการ" });
    await user.click(within(dialog).getByLabelText("ยืนยันว่าข้อมูลถูกต้อง"));
    await user.click(within(dialog).getByRole("button", { name: "ยืนยันผลการตรวจสอบรายการนี้" }));

    await waitFor(() => expect(updateReconciliationFindingDisposition).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/ถูกแก้ไขโดยผู้ใช้อื่น/)).toBeInTheDocument();
  });

  it("on SIGNED_OFF shows the immutability message", async () => {
    updateReconciliationFindingDisposition.mockRejectedValue(fakeApiError("RECONCILIATION_FINDING_SIGNED_OFF"));
    const user = userEvent.setup();
    renderPage();
    await user.click(await findFindingCardButton());
    await user.click(await screen.findByRole("button", { name: "บันทึกผลการตรวจสอบ" }));
    const dialog = await screen.findByRole("dialog", { name: "บันทึกผลการตรวจสอบรายการ" });
    await user.click(within(dialog).getByLabelText("ยืนยันว่าข้อมูลถูกต้อง"));
    await user.click(within(dialog).getByRole("button", { name: "ยืนยันผลการตรวจสอบรายการนี้" }));

    expect(await screen.findByText(/ถูกลงนามยืนยันแล้ว จึงไม่สามารถแก้ไขผลการตรวจสอบได้/)).toBeInTheDocument();
  });
});

describe("ReconciliationRunDetailPage -- sign-off", () => {
  it("requires explicit confirmation and sends only run.version", async () => {
    createReconciliationSignoff.mockResolvedValue(makeSignoff());
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByText("ลงนามยืนยันผลการตรวจสอบ"));
    const dialog = await screen.findByRole("dialog", { name: "ยืนยันการลงนามผลการตรวจสอบ" });
    expect(createReconciliationSignoff).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "ยืนยันและลงนาม" }));

    await waitFor(() => expect(createReconciliationSignoff).toHaveBeenCalledWith("run-1", { expected_version: 0 }));
    const [, body] = createReconciliationSignoff.mock.calls[0];
    expect(Object.keys(body as object)).toEqual(["expected_version"]);
  });

  it("on ALREADY_EXISTS refetches and displays the existing attestation", async () => {
    createReconciliationSignoff.mockRejectedValue(fakeApiError("RECONCILIATION_SIGNOFF_ALREADY_EXISTS"));
    fetchReconciliationSignoff
      .mockRejectedValueOnce(fakeApiError("RECONCILIATION_SIGNOFF_NOT_FOUND", "not signed", 404))
      .mockResolvedValue(makeSignoff());
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByText("ลงนามยืนยันผลการตรวจสอบ"));
    const dialog = await screen.findByRole("dialog", { name: "ยืนยันการลงนามผลการตรวจสอบ" });
    await user.click(within(dialog).getByRole("button", { name: "ยืนยันและลงนาม" }));

    await waitFor(() => expect(screen.getAllByText("ลงนามยืนยันแล้ว").length).toBeGreaterThan(0));
  });

  it("on VERSION_CONFLICT shows the conflict message and does not blind-retry", async () => {
    createReconciliationSignoff.mockRejectedValue(fakeApiError("RECONCILIATION_SIGNOFF_VERSION_CONFLICT"));
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByText("ลงนามยืนยันผลการตรวจสอบ"));
    const dialog = await screen.findByRole("dialog", { name: "ยืนยันการลงนามผลการตรวจสอบ" });
    await user.click(within(dialog).getByRole("button", { name: "ยืนยันและลงนาม" }));

    await waitFor(() => expect(createReconciliationSignoff).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/ถูกเปลี่ยนแปลงไปก่อนหน้านี้/)).toBeInTheDocument();
  });

  it("on FINDINGS_INCOMPLETE displays the backend error message", async () => {
    createReconciliationSignoff.mockRejectedValue(fakeApiError("RECONCILIATION_SIGNOFF_FINDINGS_INCOMPLETE"));
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByText("ลงนามยืนยันผลการตรวจสอบ"));
    const dialog = await screen.findByRole("dialog", { name: "ยืนยันการลงนามผลการตรวจสอบ" });
    await user.click(within(dialog).getByRole("button", { name: "ยืนยันและลงนาม" }));
    expect(await screen.findByText(/ยังมีรายการที่ยังไม่ได้ตรวจสอบ/)).toBeInTheDocument();
  });

  it("on REQUIRES_CORRECTION displays the backend error message", async () => {
    createReconciliationSignoff.mockRejectedValue(fakeApiError("RECONCILIATION_SIGNOFF_REQUIRES_CORRECTION"));
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByText("ลงนามยืนยันผลการตรวจสอบ"));
    const dialog = await screen.findByRole("dialog", { name: "ยืนยันการลงนามผลการตรวจสอบ" });
    await user.click(within(dialog).getByRole("button", { name: "ยืนยันและลงนาม" }));
    expect(await screen.findByText(/ต้องดำเนินการแก้ไข/)).toBeInTheDocument();
  });

  it("on EVIDENCE_INCONSISTENT fails closed with an admin-safe message, never computing counts itself", async () => {
    createReconciliationSignoff.mockRejectedValue(fakeApiError("RECONCILIATION_SIGNOFF_EVIDENCE_INCONSISTENT"));
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByText("ลงนามยืนยันผลการตรวจสอบ"));
    const dialog = await screen.findByRole("dialog", { name: "ยืนยันการลงนามผลการตรวจสอบ" });
    await user.click(within(dialog).getByRole("button", { name: "ยืนยันและลงนาม" }));
    expect(await screen.findByText(/ความไม่สอดคล้องของข้อมูลหลักฐาน/)).toBeInTheDocument();
  });

  it("on COVERAGE_MISMATCH fails closed and instructs the Administrator to stop", async () => {
    createReconciliationSignoff.mockRejectedValue(fakeApiError("RECONCILIATION_COVERAGE_MISMATCH"));
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByText("ลงนามยืนยันผลการตรวจสอบ"));
    const dialog = await screen.findByRole("dialog", { name: "ยืนยันการลงนามผลการตรวจสอบ" });
    await user.click(within(dialog).getByRole("button", { name: "ยืนยันและลงนาม" }));
    expect(await screen.findByText(/หยุดดำเนินการและแจ้งผู้ดูแลระบบ/)).toBeInTheDocument();
  });

  it("the sign-off button is disabled unless the run is completed", async () => {
    fetchReconciliationRun.mockResolvedValue(makeRun({ status: "running" }));
    renderPage();
    const button = await screen.findByRole("button", { name: "ลงนามยืนยันผลการตรวจสอบ" });
    expect(button).toBeDisabled();
  });
});

// Roadmap PR22F Fix Round 1 (independent review P1 #1): once a run's
// sign-off state is known, the disposition edit action must reflect it --
// but "known" here means definitively resolved, not merely "not yet
// known to be signed". The critical property under test is fail-CLOSED:
// a loading or errored sign-off query must not be treated as "unsigned"
// (which would transiently expose the edit action). Only an explicit
// resolved-and-unsigned state (the default beforeEach's 404 NOT_FOUND,
// exercised by the existing "administrator sees disposition and sign-off
// actions" test above) opens the action.
describe("ReconciliationRunDetailPage -- disposition edit gating (sign-off fail-closed)", () => {
  it("hides the disposition edit action once the run's sign-off has loaded", async () => {
    fetchReconciliationSignoff.mockResolvedValue(makeSignoff());
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getAllByText("ลงนามยืนยันแล้ว").length).toBeGreaterThan(0));
    await user.click(await findFindingCardButton());
    await screen.findByRole("dialog");
    expect(screen.queryByRole("button", { name: "บันทึกผลการตรวจสอบ" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "แก้ไขผลการตรวจสอบ" })).not.toBeInTheDocument();
    expect(updateReconciliationFindingDisposition).not.toHaveBeenCalled();
  });

  it("does not expose the disposition edit action while the sign-off query is still loading", async () => {
    fetchReconciliationSignoff.mockImplementation(() => new Promise(() => {}));
    const user = userEvent.setup();
    renderPage();
    await user.click(await findFindingCardButton());
    await screen.findByRole("dialog");
    expect(screen.queryByRole("button", { name: "บันทึกผลการตรวจสอบ" })).not.toBeInTheDocument();
  });

  it("does not expose the disposition edit action when the sign-off query errors for a reason other than not-found", async () => {
    fetchReconciliationSignoff.mockRejectedValue(new Error("network boom"));
    const user = userEvent.setup();
    renderPage();
    await user.click(await findFindingCardButton());
    await screen.findByRole("dialog");
    expect(screen.queryByRole("button", { name: "บันทึกผลการตรวจสอบ" })).not.toBeInTheDocument();
  });

  it("keeps the disposition edit action available once sign-off resolves to confirmed-unsigned", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await findFindingCardButton());
    expect(await screen.findByRole("button", { name: "บันทึกผลการตรวจสอบ" })).toBeInTheDocument();
  });

  it("keeps the backend's own SIGNED_OFF error handling as defense-in-depth if a stale UI still submits", async () => {
    // The dialog-level SIGNED_OFF regression above (in the "disposition"
    // describe block) already proves the backend response is still
    // handled correctly -- this is a documentation-only cross-reference,
    // not a duplicate assertion.
    updateReconciliationFindingDisposition.mockRejectedValue(fakeApiError("RECONCILIATION_FINDING_SIGNED_OFF"));
    const user = userEvent.setup();
    renderPage();
    await user.click(await findFindingCardButton());
    await user.click(await screen.findByRole("button", { name: "บันทึกผลการตรวจสอบ" }));
    const dialog = await screen.findByRole("dialog", { name: "บันทึกผลการตรวจสอบรายการ" });
    await user.click(within(dialog).getByLabelText("ยืนยันว่าข้อมูลถูกต้อง"));
    await user.click(within(dialog).getByRole("button", { name: "ยืนยันผลการตรวจสอบรายการนี้" }));
    expect(await screen.findByText(/ถูกลงนามยืนยันแล้ว จึงไม่สามารถแก้ไขผลการตรวจสอบได้/)).toBeInTheDocument();
  });
});

// Roadmap PR22F Fix Round 1 (independent review P1 #2): the run detail
// page's finding filters must cover all four backend-supported params
// (code, severity, disposition, equipment_id), every change must hit the
// backend rather than filtering already-loaded rows client-side, and the
// query key (reconciliationKeys.findings) must differentiate distinct
// filter combinations -- proven here indirectly by asserting each
// distinct selection produces a distinct backend request.
describe("ReconciliationRunDetailPage -- finding filters (code + equipment_id)", () => {
  it("renders exactly the known PR22C finding codes as filter options, plus the all-codes default", async () => {
    renderPage();
    const codeSelect = await screen.findByLabelText("ประเภทปัญหา");
    expect(within(codeSelect).getAllByRole("option")).toHaveLength(10);
    expect(within(codeSelect).getByText("ทั้งหมด")).toBeInTheDocument();
  });

  it("sends the selected finding code to the backend as a server-side filter", async () => {
    const user = userEvent.setup();
    renderPage();
    const codeSelect = await screen.findByLabelText("ประเภทปัญหา");
    await user.selectOptions(codeSelect, "DUPLICATE_EXACT");

    await waitFor(() =>
      expect(fetchReconciliationFindings).toHaveBeenLastCalledWith(
        "run-1",
        expect.objectContaining({ code: "DUPLICATE_EXACT", cursor: null })
      )
    );
  });

  it("looks up equipment via the existing equipment search API rather than a raw UUID field, and sends its id to the backend", async () => {
    searchEquipment.mockResolvedValue({ items: [makeEquipment()], next_cursor: null, total: 1 });
    const user = userEvent.setup();
    renderPage();

    const equipmentInput = await screen.findByLabelText("เครื่องมือ");
    expect(equipmentInput.tagName).toBe("INPUT");
    await user.type(equipmentInput, "Infusion");
    await waitFor(() => expect(searchEquipment).toHaveBeenCalledWith(expect.objectContaining({ q: "Infusion" })));
    await user.click(await screen.findByText("Infusion Pump 9"));

    await waitFor(() =>
      expect(fetchReconciliationFindings).toHaveBeenLastCalledWith(
        "run-1",
        expect.objectContaining({ equipment_id: "equip-9", cursor: null })
      )
    );
  });

  it("sends all four filters together, each as its own server-side param", async () => {
    searchEquipment.mockResolvedValue({ items: [makeEquipment()], next_cursor: null, total: 1 });
    const user = userEvent.setup();
    renderPage();

    await user.selectOptions(await screen.findByLabelText("สถานะการตรวจ"), "confirmed_valid");
    await user.selectOptions(screen.getByLabelText("ความรุนแรง"), "high");
    await user.selectOptions(screen.getByLabelText("ประเภทปัญหา"), "DUPLICATE_EXACT");
    await user.type(screen.getByLabelText("เครื่องมือ"), "Infusion");
    await user.click(await screen.findByText("Infusion Pump 9"));

    await waitFor(() =>
      expect(fetchReconciliationFindings).toHaveBeenLastCalledWith(
        "run-1",
        expect.objectContaining({
          disposition: "confirmed_valid",
          severity: "high",
          code: "DUPLICATE_EXACT",
          equipment_id: "equip-9",
          cursor: null,
        })
      )
    );
  });

  it("resets pagination (a fresh null cursor) whenever a filter changes rather than carrying over a stale cursor", async () => {
    const user = userEvent.setup();
    renderPage();
    const severitySelect = await screen.findByLabelText("ความรุนแรง");
    await waitFor(() => expect(fetchReconciliationFindings).toHaveBeenCalledWith("run-1", expect.objectContaining({ cursor: null })));
    fetchReconciliationFindings.mockClear();

    await user.selectOptions(severitySelect, "high");

    await waitFor(() =>
      expect(fetchReconciliationFindings).toHaveBeenCalledWith("run-1", expect.objectContaining({ severity: "high", cursor: null }))
    );
  });
});
