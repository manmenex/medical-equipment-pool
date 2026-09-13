import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CutoverReadinessRunDetailPage } from "@/pages/CutoverReadinessRunDetailPage";
import type { UserProfile } from "@/types";
import type {
  CutoverDecisionDetail,
  CutoverGateEvaluationItem,
  CutoverGateEvaluationResponse,
  CutoverGateStatus,
  CutoverReadinessRunDetail,
} from "@/types/cutoverReadiness";

const fetchCutoverReadinessRun = vi.fn();
const fetchCutoverGateEvaluation = vi.fn();
const fetchCutoverDecision = vi.fn();
const createCutoverDecision = vi.fn();

vi.mock("@/services/cutoverReadiness", async () => {
  const actual = await vi.importActual<typeof import("@/services/cutoverReadiness")>("@/services/cutoverReadiness");
  return {
    ...actual,
    fetchCutoverReadinessRun: (...args: unknown[]) => fetchCutoverReadinessRun(...args),
    fetchCutoverGateEvaluation: (...args: unknown[]) => fetchCutoverGateEvaluation(...args),
    fetchCutoverDecision: (...args: unknown[]) => fetchCutoverDecision(...args),
    createCutoverDecision: (...args: unknown[]) => createCutoverDecision(...args),
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

function makeRun(overrides: Partial<CutoverReadinessRunDetail> = {}): CutoverReadinessRunDetail {
  return {
    id: "run-1",
    status: "completed",
    version: 2,
    created_by_user_id: "user-9",
    created_at: "2026-07-01T00:00:00Z",
    completed_at: "2026-07-01T00:05:00Z",
    completed_by_user_id: "user-9",
    application_baseline_sha: "b".repeat(40),
    database_migration_head: "0022_cutover_go_no_go_decision",
    source_of_truth_strategy: "hard_cutover",
    cutover_instant: "2026-08-01T00:00:00Z",
    freeze_window_reference: null,
    supersedes_run_id: null,
    equipment_master_import_source_id: "src-1",
    legacy_migration_authority_id: "auth-1",
    legacy_coverage_id: "cov-1",
    reconciliation_run_id: "recon-1",
    reconciliation_signoff_id: "signoff-1",
    current_state_verified_at: "2026-07-01T00:00:00Z",
    current_state_verified_by_user_id: "user-9",
    current_state_verification_scope_count: 10,
    current_state_verification_reference: "ref",
    pilot_ward_id: null,
    operational_approver_reference: null,
    ...overrides,
  };
}

function makeItem(overrides: Partial<CutoverGateEvaluationItem> = {}): CutoverGateEvaluationItem {
  return {
    gate: "A",
    category: "info",
    code: "GATE_A_OK",
    message: "ทดสอบ",
    manual_attestation_required: false,
    detail: {},
    ...overrides,
  };
}

function makeGateEvaluation(items: CutoverGateEvaluationItem[] = []): CutoverGateEvaluationResponse {
  const gates = (["A", "B", "C", "D", "E", "F"] as const).map((gate) => {
    const gateItems = items.filter((i) => i.gate === gate);
    const status: CutoverGateStatus = gateItems.some((i) => i.category === "blocker")
      ? "blocker"
      : gateItems.some((i) => i.category === "warning")
        ? "warning"
        : "satisfied";
    return { gate, mandatory: true, status };
  });
  return {
    cutover_readiness_run_id: "run-1",
    evaluated_at: "2026-08-01T00:00:00Z",
    has_blocker: items.some((i) => i.category === "blocker"),
    gates,
    items,
  };
}

function makeDecision(overrides: Partial<CutoverDecisionDetail> = {}): CutoverDecisionDetail {
  return {
    id: "decision-1",
    cutover_readiness_run_id: "run-1",
    decision: "NO_GO",
    recorded_by_user_id: "user-9",
    recorded_at: "2026-08-02T00:00:00Z",
    run_version_at_decision: 2,
    acknowledged_warning_codes: [],
    no_go_reason: null,
    ...overrides,
  };
}

beforeEach(() => {
  mockUser = makeUser("administrator");
  fetchCutoverReadinessRun.mockResolvedValue(makeRun());
  fetchCutoverGateEvaluation.mockResolvedValue(makeGateEvaluation([]));
  fetchCutoverDecision.mockRejectedValue(fakeApiError("CUTOVER_DECISION_NOT_FOUND", "not found", 404));
});

afterEach(() => {
  vi.resetAllMocks();
});

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/cutover-readiness/run-1"]}>
        <Routes>
          <Route path="/cutover-readiness/:runId" element={<CutoverReadinessRunDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

// A/S -- every role can view; gate evaluation is skipped (not treated as
// failed) for a non-completed run.
describe("CutoverReadinessRunDetailPage -- read UX", () => {
  it("renders run summary once loaded", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("บันทึกหลักฐานครบถ้วน")).toBeInTheDocument());
    expect(fetchCutoverReadinessRun).toHaveBeenCalledWith("run-1");
  });

  it("shows an error state with retry if the run fails to load", async () => {
    fetchCutoverReadinessRun.mockRejectedValue(new Error("boom"));
    renderPage();
    await waitFor(() => expect(screen.getByText(/ไม่สามารถโหลดข้อมูลรอบความพร้อมได้/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "ลองใหม่" })).toBeInTheDocument();
  });

  it("does not call gate-evaluation for a non-completed run, and does not present it as failed readiness", async () => {
    fetchCutoverReadinessRun.mockResolvedValue(makeRun({ status: "pending" }));
    renderPage();
    await waitFor(() => expect(screen.getByText("รอดำเนินการ")).toBeInTheDocument());
    expect(fetchCutoverGateEvaluation).not.toHaveBeenCalled();
    expect(screen.getByText(/รอบนี้ยังไม่บันทึกหลักฐานครบถ้วน/)).toBeInTheDocument();
  });

  it("is visible for every authenticated role (mirrors backend VIEW_AND_REPORT_ROLES)", async () => {
    mockUser = makeUser("read_only");
    renderPage();
    await waitFor(() => expect(fetchCutoverReadinessRun).toHaveBeenCalled());
  });
});

// H/I/J/K -- Gate presentation.
describe("CutoverReadinessRunDetailPage -- gate presentation", () => {
  it("shows the fail-closed summary and a blocker item clearly when a blocker exists", async () => {
    fetchCutoverGateEvaluation.mockResolvedValue(
      makeGateEvaluation([makeItem({ gate: "A", category: "blocker", code: "GATE_A_MIGRATION_HEAD_STALE", message: "หัวข้อมูลไม่ตรงกัน" })])
    );
    renderPage();
    await waitFor(() => expect(screen.getByText("ยังไม่พร้อมสำหรับการอนุมัติ GO")).toBeInTheDocument());
    expect(screen.getByText("หัวข้อมูลไม่ตรงกัน")).toBeInTheDocument();
    expect(screen.getAllByText("ตัวบล็อก").length).toBeGreaterThan(0);
  });

  it("shows the warnings-present summary and manual-attestation copy when only warnings exist", async () => {
    fetchCutoverGateEvaluation.mockResolvedValue(
      makeGateEvaluation([
        makeItem({ gate: "F", category: "warning", code: "GATE_F_STAFF_TRAINING_NOT_AUTOMATED", message: "ต้องยืนยันการฝึกอบรม", manual_attestation_required: true }),
      ])
    );
    renderPage();
    await waitFor(() => expect(screen.getByText("ไม่มีรายการที่เป็นตัวบล็อก แต่ยังมีรายการที่ต้องรับทราบ")).toBeInTheDocument());
    expect(screen.getByText("ต้องยืนยันการฝึกอบรม")).toBeInTheDocument();
    expect(screen.getByText(/รายการนี้ระบบไม่สามารถตรวจสอบอัตโนมัติได้ ต้องตรวจสอบโดยผู้รับผิดชอบ/)).toBeInTheDocument();
  });

  it("shows the all-clear summary and info items when neither blockers nor warnings exist", async () => {
    fetchCutoverGateEvaluation.mockResolvedValue(makeGateEvaluation([makeItem({ gate: "E", category: "info", message: "ตรวจสอบสถานะแล้ว" })]));
    renderPage();
    await waitFor(() => expect(screen.getByText("ไม่พบตัวบล็อกหรือคำเตือนจากการตรวจอัตโนมัติ")).toBeInTheDocument());
    expect(screen.getByText("ตรวจสอบสถานะแล้ว")).toBeInTheDocument();
    expect(screen.getByText("ข้อมูล")).toBeInTheDocument();
  });

  it("links Gate E to the existing Issue workflow rather than a new re-issue page", async () => {
    fetchCutoverGateEvaluation.mockResolvedValue(makeGateEvaluation([makeItem({ gate: "E", category: "info" })]));
    renderPage();
    const link = await screen.findByRole("link", { name: "ไปหน้าส่งเครื่อง" });
    expect(link).toHaveAttribute("href", "/borrow");
  });
});

// B/C/D/E/F/G -- fail-closed decision-action visibility.
describe("CutoverReadinessRunDetailPage -- fail-closed decision action visibility", () => {
  it("Administrator sees GO/NO-GO actions once every precondition resolves", async () => {
    renderPage();
    expect(await screen.findByRole("button", { name: "อนุมัติ GO" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ไม่อนุมัติ NO-GO" })).toBeInTheDocument();
  });

  it("disables GO but keeps NO-GO enabled while a blocker exists", async () => {
    fetchCutoverGateEvaluation.mockResolvedValue(makeGateEvaluation([makeItem({ category: "blocker" })]));
    renderPage();
    expect(await screen.findByRole("button", { name: "อนุมัติ GO" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "ไม่อนุมัติ NO-GO" })).toBeEnabled();
  });

  it("staff/read_only never see the decision action", async () => {
    for (const role of ["equipment_pool_staff", "read_only"] as const) {
      mockUser = makeUser(role);
      const { unmount } = renderPage();
      await waitFor(() => expect(screen.getByText("รอบนี้ยังไม่มีการบันทึกผล GO/NO-GO")).toBeInTheDocument());
      expect(screen.queryByRole("button", { name: "อนุมัติ GO" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "ไม่อนุมัติ NO-GO" })).not.toBeInTheDocument();
      unmount();
    }
  });

  it("hides the decision action while the decision query is still loading", async () => {
    fetchCutoverDecision.mockImplementation(() => new Promise(() => {}));
    renderPage();
    await waitFor(() => expect(fetchCutoverGateEvaluation).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "อนุมัติ GO" })).not.toBeInTheDocument();
  });

  it("hides the decision action when the decision query errors for a reason other than not-found", async () => {
    fetchCutoverDecision.mockRejectedValue(new Error("network boom"));
    renderPage();
    await waitFor(() => expect(screen.getByText(/ไม่สามารถตรวจสอบผลการอนุมัติได้/)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "อนุมัติ GO" })).not.toBeInTheDocument();
  });

  it("hides the decision action while the gate-evaluation query is still loading", async () => {
    fetchCutoverGateEvaluation.mockImplementation(() => new Promise(() => {}));
    renderPage();
    await waitFor(() => expect(screen.getByText("กำลังตรวจสอบความพร้อม...")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "อนุมัติ GO" })).not.toBeInTheDocument();
  });

  it("shows the immutable decision display and no action once a decision already exists", async () => {
    fetchCutoverDecision.mockResolvedValue(makeDecision({ decision: "GO", acknowledged_warning_codes: ["GATE_F_STAFF_TRAINING_NOT_AUTOMATED"] }));
    renderPage();
    await waitFor(() => expect(screen.getByText("อนุมัติเปลี่ยนระบบ (GO)")).toBeInTheDocument());
    expect(screen.getByText("GATE_F_STAFF_TRAINING_NOT_AUTOMATED")).toBeInTheDocument();
    expect(screen.getByText(/ผลการอนุมัตินี้เป็นข้อมูลถาวร/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "อนุมัติ GO" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "ไม่อนุมัติ NO-GO" })).not.toBeInTheDocument();
  });

  it("displays the no_go_reason when present on an existing NO_GO decision", async () => {
    fetchCutoverDecision.mockResolvedValue(makeDecision({ decision: "NO_GO", no_go_reason: "หอผู้ป่วยนำร่องยังไม่พร้อม" }));
    renderPage();
    await waitFor(() => expect(screen.getByText("หอผู้ป่วยนำร่องยังไม่พร้อม")).toBeInTheDocument());
  });
});

describe("CutoverReadinessRunDetailPage -- GO/NO-GO submission", () => {
  it("GO checkboxes are not preselected, and the request contains exactly the checked codes", async () => {
    createCutoverDecision.mockResolvedValue(makeDecision({ decision: "GO" }));
    fetchCutoverGateEvaluation.mockResolvedValue(
      makeGateEvaluation([
        makeItem({ gate: "A", category: "warning", code: "WARN_A" }),
        makeItem({ gate: "F", category: "warning", code: "WARN_F" }),
      ])
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "อนุมัติ GO" }));
    const dialog = await screen.findByRole("dialog", { name: "ยืนยันอนุมัติเปลี่ยนระบบ (GO)" });
    const checkboxes = within(dialog).getAllByRole("checkbox");
    expect(checkboxes).toHaveLength(2);
    checkboxes.forEach((cb) => expect(cb).not.toBeChecked());

    const confirmButton = within(dialog).getByRole("button", { name: "ยืนยันและอนุมัติ GO" });
    expect(confirmButton).toBeDisabled();
    await user.click(checkboxes[0]);
    expect(confirmButton).toBeDisabled();
    await user.click(checkboxes[1]);
    expect(confirmButton).toBeEnabled();
    await user.click(confirmButton);

    await waitFor(() =>
      expect(createCutoverDecision).toHaveBeenCalledWith("run-1", {
        expected_version: 2,
        decision: "GO",
        acknowledged_warning_codes: ["WARN_A", "WARN_F"],
        no_go_reason: undefined,
      })
    );
  });

  it("never sends a client-computed eligibility/readiness field -- only the four documented DecisionCreateRequest fields", async () => {
    createCutoverDecision.mockResolvedValue(makeDecision({ decision: "NO_GO" }));
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "ไม่อนุมัติ NO-GO" }));
    const dialog = await screen.findByRole("dialog", { name: "ยืนยันไม่อนุมัติเปลี่ยนระบบ (NO-GO)" });
    await user.click(within(dialog).getByRole("button", { name: "ยืนยันและไม่อนุมัติ NO-GO" }));

    await waitFor(() => expect(createCutoverDecision).toHaveBeenCalled());
    const [, payload] = createCutoverDecision.mock.calls[0];
    expect(Object.keys(payload as object).sort()).toEqual(
      ["acknowledged_warning_codes", "decision", "expected_version", "no_go_reason"].sort()
    );
  });

  it("NO_GO remains available and submits the trimmed reason even while a blocker exists", async () => {
    createCutoverDecision.mockResolvedValue(makeDecision({ decision: "NO_GO", no_go_reason: "ยังไม่พร้อม" }));
    fetchCutoverGateEvaluation.mockResolvedValue(makeGateEvaluation([makeItem({ category: "blocker" })]));
    const user = userEvent.setup();
    renderPage();
    const noGoButton = await screen.findByRole("button", { name: "ไม่อนุมัติ NO-GO" });
    expect(noGoButton).toBeEnabled();
    await user.click(noGoButton);
    const dialog = await screen.findByRole("dialog", { name: "ยืนยันไม่อนุมัติเปลี่ยนระบบ (NO-GO)" });
    await user.type(within(dialog).getByLabelText("เหตุผล (ถ้ามี)"), "  ยังไม่พร้อม  ");
    await user.click(within(dialog).getByRole("button", { name: "ยืนยันและไม่อนุมัติ NO-GO" }));

    await waitFor(() =>
      expect(createCutoverDecision).toHaveBeenCalledWith("run-1", {
        expected_version: 2,
        decision: "NO_GO",
        acknowledged_warning_codes: [],
        no_go_reason: "ยังไม่พร้อม",
      })
    );
  });

  it("on CUTOVER_DECISION_STALE_VERSION shows the conflict message and refetches run/gates/decision", async () => {
    createCutoverDecision.mockRejectedValue(fakeApiError("CUTOVER_DECISION_STALE_VERSION"));
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "ไม่อนุมัติ NO-GO" }));
    const dialog = await screen.findByRole("dialog", { name: "ยืนยันไม่อนุมัติเปลี่ยนระบบ (NO-GO)" });
    fetchCutoverReadinessRun.mockClear();
    await user.click(within(dialog).getByRole("button", { name: "ยืนยันและไม่อนุมัติ NO-GO" }));

    expect(await screen.findByText(/เปลี่ยนแปลงไปก่อนหน้านี้/)).toBeInTheDocument();
    await waitFor(() => expect(fetchCutoverReadinessRun).toHaveBeenCalled());
  });

  it("on CUTOVER_DECISION_ALREADY_EXISTS closes the dialog and refetches the now-immutable decision", async () => {
    createCutoverDecision.mockRejectedValue(fakeApiError("CUTOVER_DECISION_ALREADY_EXISTS"));
    fetchCutoverDecision
      .mockRejectedValueOnce(fakeApiError("CUTOVER_DECISION_NOT_FOUND", "not found", 404))
      .mockResolvedValue(makeDecision({ decision: "GO" }));
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "ไม่อนุมัติ NO-GO" }));
    const dialog = await screen.findByRole("dialog", { name: "ยืนยันไม่อนุมัติเปลี่ยนระบบ (NO-GO)" });
    await user.click(within(dialog).getByRole("button", { name: "ยืนยันและไม่อนุมัติ NO-GO" }));

    await waitFor(() => expect(screen.getByText("อนุมัติเปลี่ยนระบบ (GO)")).toBeInTheDocument());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("on CUTOVER_DECISION_BLOCKED_BY_READINESS shows the message and does not close the dialog", async () => {
    createCutoverDecision.mockRejectedValue(fakeApiError("CUTOVER_DECISION_BLOCKED_BY_READINESS", "blocked", 422));
    fetchCutoverGateEvaluation.mockResolvedValue(
      makeGateEvaluation([makeItem({ gate: "A", category: "warning", code: "WARN_A" })])
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "อนุมัติ GO" }));
    const dialog = await screen.findByRole("dialog", { name: "ยืนยันอนุมัติเปลี่ยนระบบ (GO)" });
    await user.click(within(dialog).getByRole("checkbox"));
    await user.click(within(dialog).getByRole("button", { name: "ยืนยันและอนุมัติ GO" }));

    expect(await screen.findByText(/ยังมีรายการที่เป็นตัวบล็อก/)).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("rejects an escape-key close and background click while submitting is not possible mid-request (no double-submit)", async () => {
    let resolveCreate: (value: CutoverDecisionDetail) => void = () => {};
    createCutoverDecision.mockImplementation(
      () =>
        new Promise<CutoverDecisionDetail>((resolve) => {
          resolveCreate = resolve;
        })
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "ไม่อนุมัติ NO-GO" }));
    const dialog = await screen.findByRole("dialog", { name: "ยืนยันไม่อนุมัติเปลี่ยนระบบ (NO-GO)" });
    const confirmButton = within(dialog).getByRole("button", { name: "ยืนยันและไม่อนุมัติ NO-GO" });
    await user.click(confirmButton);
    expect(confirmButton).toBeDisabled();
    await user.click(confirmButton);
    expect(createCutoverDecision).toHaveBeenCalledTimes(1);
    resolveCreate(makeDecision({ decision: "NO_GO" }));
  });
});
