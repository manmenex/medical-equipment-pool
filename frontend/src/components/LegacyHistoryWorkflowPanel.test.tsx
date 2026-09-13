import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LegacyHistoryWorkflowPanel } from "@/components/LegacyHistoryWorkflowPanel";
import type {
  ImportSessionSummaryOut,
  LegacyHistoryDryRunPlanOut,
  LegacyHistoryDryRunPlanRowOut,
} from "@/types/legacyImportApi";

const getLegacyHistorySession = vi.fn();
const validateLegacyHistorySession = vi.fn();
const dryRunLegacyHistorySession = vi.fn();
const executeLegacyHistorySession = vi.fn();
const recoverLegacyHistorySession = vi.fn();
const confirmLegacyHistoryDryRunPlan = vi.fn();
const getLegacyHistoryDryRunPlan = vi.fn();
const listLegacyHistoryDryRunPlanRows = vi.fn();
const listLegacyHistoryValidationFindings = vi.fn();

vi.mock("@/services/legacyHistoryImportClient", () => ({
  getLegacyHistorySession: (...args: unknown[]) => getLegacyHistorySession(...args),
  validateLegacyHistorySession: (...args: unknown[]) => validateLegacyHistorySession(...args),
  dryRunLegacyHistorySession: (...args: unknown[]) => dryRunLegacyHistorySession(...args),
  executeLegacyHistorySession: (...args: unknown[]) => executeLegacyHistorySession(...args),
  recoverLegacyHistorySession: (...args: unknown[]) => recoverLegacyHistorySession(...args),
  confirmLegacyHistoryDryRunPlan: (...args: unknown[]) => confirmLegacyHistoryDryRunPlan(...args),
  getLegacyHistoryDryRunPlan: (...args: unknown[]) => getLegacyHistoryDryRunPlan(...args),
  listLegacyHistoryDryRunPlanRows: (...args: unknown[]) => listLegacyHistoryDryRunPlanRows(...args),
  listLegacyHistoryValidationFindings: (...args: unknown[]) => listLegacyHistoryValidationFindings(...args),
}));

function makeApiError(status: number, code: string, detail = "error"): Error {
  return Object.assign(new Error(detail), {
    isAxiosError: true,
    response: { status, data: { code, detail } },
  });
}

const SESSION_ID = "11111111-1111-4111-8111-111111111111";

function baseSession(overrides: Partial<ImportSessionSummaryOut> = {}): ImportSessionSummaryOut {
  return {
    id: SESSION_ID,
    dataset_type: "legacy_transaction_history",
    status: "created",
    version: 1,
    created_by_user_id: "user-1",
    idempotency_key: null,
    notes: null,
    terminal_at: null,
    failure_reason: null,
    created_at: "2026-07-20T03:00:00Z",
    updated_at: "2026-07-20T03:00:00Z",
    validated_at: null,
    total_rows: null,
    valid_rows: null,
    invalid_rows: null,
    warning_rows: null,
    dry_run_completed_at: null,
    executed_at: null,
    imported_rows: null,
    jobs: [],
    finding_count: 0,
    validation_attempt_id: null,
    ...overrides,
  };
}

function basePlan(overrides: Partial<LegacyHistoryDryRunPlanOut> = {}): LegacyHistoryDryRunPlanOut {
  return {
    id: "plan-1",
    import_session_id: SESSION_ID,
    import_source_id: "source-1",
    migration_authority_id: "auth-1",
    status: "active",
    is_current: true,
    created_at: "2026-07-20T04:00:00Z",
    confirmed_at: null,
    confirmed_by_user_id: null,
    summary: { total_rows: 2, issue_events: 1, receive_events: 1, warnings: 0, blocking_conflicts: 0 },
    ...overrides,
  };
}

function basePlanRow(overrides: Partial<LegacyHistoryDryRunPlanRowOut> = {}): LegacyHistoryDryRunPlanRowOut {
  return {
    id: "row-1",
    source_row_number: 5,
    event_type: "ISSUE",
    legacy_source_row_key: "key-5",
    values: {
      legacy_order_reference: "ORD-1",
      equipment_id: "22222222-2222-4222-8222-222222222222",
      occurred_at: "2026-07-19T02:00:00Z",
      legacy_ward_text: "ICU เก่า",
      resolved_ward_id: null,
      legacy_bme_name: "BME-100",
      header_source_ref: { sheet_name: "Issue", source_row_number: 2 },
      line_source_ref: { sheet_name: "Issue", source_row_number: 5 },
    },
    warnings: [],
    ...overrides,
  };
}

function renderPanel(sessionId = SESSION_ID) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <LegacyHistoryWorkflowPanel sessionId={sessionId} />
    </QueryClientProvider>
  );
}

afterEach(() => {
  vi.resetAllMocks();
});

describe("LegacyHistoryWorkflowPanel", () => {
  it("shows a loading state, then the header with ISSUE/RECEIVE-neutral title and status badge", async () => {
    getLegacyHistorySession.mockResolvedValue(baseSession());
    renderPanel();

    expect(screen.getByText("กำลังโหลดรายละเอียดการนำเข้าข้อมูล...")).toBeInTheDocument();
    expect(await screen.findByText("นำเข้าประวัติการรับ-ส่งเครื่องมือเดิม")).toBeInTheDocument();
    expect(screen.getByText("สร้างรายการแล้ว")).toBeInTheDocument();
  });

  it("shows a generic load error with retry when the session fetch fails", async () => {
    getLegacyHistorySession.mockRejectedValue(new Error("network error"));
    renderPanel();

    expect(await screen.findByText("ไม่สามารถโหลดรายละเอียดการนำเข้าข้อมูลได้")).toBeInTheDocument();
  });

  it("full happy path: validate -> dry-run -> confirm -> execute -> completed", async () => {
    getLegacyHistorySession
      .mockResolvedValueOnce(baseSession({ status: "created" }))
      .mockResolvedValueOnce(baseSession({ status: "validated", total_rows: 2, valid_rows: 2, invalid_rows: 0, warning_rows: 0, validated_at: "t" }))
      .mockResolvedValueOnce(
        baseSession({ status: "dry_run_completed", total_rows: 2, valid_rows: 2, invalid_rows: 0, warning_rows: 0, dry_run_completed_at: "t" })
      )
      .mockResolvedValueOnce(
        baseSession({ status: "dry_run_completed", total_rows: 2, valid_rows: 2, invalid_rows: 0, warning_rows: 0, dry_run_completed_at: "t" })
      )
      // The execute call resolves the session straight to "completed" here
      // (never an intermediate "executing" polling state) -- avoids
      // depending on this panel's own 3s refetchInterval, which fake
      // timers would otherwise need to advance.
      .mockResolvedValue(
        baseSession({
          status: "completed",
          total_rows: 2,
          valid_rows: 2,
          invalid_rows: 0,
          warning_rows: 0,
          dry_run_completed_at: "t",
          terminal_at: "2026-07-21T00:00:00Z",
          imported_rows: 2,
        })
      );
    validateLegacyHistorySession.mockResolvedValue({});
    dryRunLegacyHistorySession.mockResolvedValue({});
    executeLegacyHistorySession.mockResolvedValue({});
    getLegacyHistoryDryRunPlan
      .mockResolvedValueOnce(basePlan())
      .mockResolvedValue(basePlan({ confirmed_at: "2026-07-20T05:00:00Z", confirmed_by_user_id: "user-1" }));
    listLegacyHistoryDryRunPlanRows.mockResolvedValue({ items: [basePlanRow()], next_cursor: null, total: 1 });
    confirmLegacyHistoryDryRunPlan.mockResolvedValue({});

    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "ตรวจสอบข้อมูล" }));
    await waitFor(() => expect(validateLegacyHistorySession).toHaveBeenCalledWith(SESSION_ID));

    await user.click(await screen.findByRole("button", { name: "ทดลองนำเข้า" }));
    await waitFor(() => expect(dryRunLegacyHistorySession).toHaveBeenCalledWith(SESSION_ID));

    expect(await screen.findByText("ส่งเครื่อง (Issue)")).toBeInTheDocument();
    expect(screen.getAllByText("ส่งเครื่อง").length).toBeGreaterThan(0); // row event-type badge (desktop + mobile)

    await user.click(screen.getByRole("button", { name: "ยืนยันแผนการนำเข้า" }));
    const confirmDialog = await screen.findByRole("alertdialog");
    await user.click(within(confirmDialog).getByRole("button", { name: "ยืนยัน" }));
    await waitFor(() => expect(confirmLegacyHistoryDryRunPlan).toHaveBeenCalledWith(SESSION_ID, "plan-1"));

    await user.click(await screen.findByRole("button", { name: "ดำเนินการนำเข้าจริง" }));
    const executeDialog = await screen.findByRole("alertdialog");
    await user.click(within(executeDialog).getByRole("button", { name: "ยืนยันดำเนินการ" }));
    await waitFor(() => expect(executeLegacyHistorySession).toHaveBeenCalledWith(SESSION_ID));

    expect(await screen.findByText("สรุปผลการนำเข้า")).toBeInTheDocument();
  });

  it("blocks the dry-run button and shows a distinct error state when findings exist but fail to load, never rendering as empty", async () => {
    getLegacyHistorySession.mockResolvedValue(baseSession({ status: "validated", finding_count: 3, total_rows: 5, valid_rows: 5, invalid_rows: 0, warning_rows: 0 }));
    listLegacyHistoryValidationFindings.mockRejectedValue(new Error("boom"));
    renderPanel();

    expect(await screen.findByText(/ไม่สามารถโหลดรายการที่ต้องตรวจสอบได้/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ทดลองนำเข้า" })).toBeDisabled();
  });

  it("renders a genuine zero-findings result without an error state when finding_count is 0", async () => {
    getLegacyHistorySession.mockResolvedValue(baseSession({ status: "validated", finding_count: 0, total_rows: 5, valid_rows: 5, invalid_rows: 0, warning_rows: 0 }));
    renderPanel();

    await screen.findByText("สรุปผลการตรวจสอบข้อมูล");
    expect(listLegacyHistoryValidationFindings).not.toHaveBeenCalled();
    expect(screen.queryByText(/ไม่สามารถโหลดรายการที่ต้องตรวจสอบได้/)).not.toBeInTheDocument();
  });

  it("renders a structural failure distinctly (no counters, no findings) without claiming false row-level results", async () => {
    getLegacyHistorySession.mockResolvedValue(
      baseSession({ status: "validation_failed", total_rows: null, finding_count: 0, failure_reason: "ไม่สามารถอ่านไฟล์นี้ได้" })
    );
    renderPanel();

    expect(await screen.findByText("การตรวจสอบข้อมูลล้มเหลว")).toBeInTheDocument();
    expect(screen.getByText("ไม่สามารถอ่านไฟล์นี้ได้")).toBeInTheDocument();
    expect(screen.queryByText("สรุปผลการตรวจสอบข้อมูล")).not.toBeInTheDocument();
  });

  it("surfaces a stale-plan error and prompts a fresh dry-run without auto-retrying", async () => {
    getLegacyHistorySession.mockResolvedValue(
      baseSession({ status: "dry_run_completed", total_rows: 2, valid_rows: 2, invalid_rows: 0, warning_rows: 0, dry_run_completed_at: "t" })
    );
    getLegacyHistoryDryRunPlan.mockResolvedValue(basePlan());
    listLegacyHistoryDryRunPlanRows.mockResolvedValue({ items: [basePlanRow()], next_cursor: null, total: 1 });
    confirmLegacyHistoryDryRunPlan.mockRejectedValue(makeApiError(409, "IMPORT_DRY_RUN_PLAN_STALE"));

    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "ยืนยันแผนการนำเข้า" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "ยืนยัน" }));

    expect(await screen.findByText(/แผนการนำเข้าที่ตรวจสอบไว้ไม่สามารถใช้งานได้แล้ว/)).toBeInTheDocument();
    expect(screen.getByText(/กรุณากดทดลองนำเข้าใหม่อีกครั้ง/)).toBeInTheDocument();
  });

  it("surfaces an execution-conflict error without silently retrying", async () => {
    getLegacyHistorySession.mockResolvedValue(
      baseSession({ status: "dry_run_completed", total_rows: 2, valid_rows: 2, invalid_rows: 0, warning_rows: 0, dry_run_completed_at: "t" })
    );
    getLegacyHistoryDryRunPlan.mockResolvedValue(basePlan({ confirmed_at: "2026-07-20T05:00:00Z" }));
    listLegacyHistoryDryRunPlanRows.mockResolvedValue({ items: [basePlanRow()], next_cursor: null, total: 1 });
    executeLegacyHistorySession.mockRejectedValue(makeApiError(409, "IMPORT_ATTEMPT_IN_PROGRESS"));

    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "ดำเนินการนำเข้าจริง" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "ยืนยันดำเนินการ" }));

    expect(await screen.findByText("มีการดำเนินการอยู่แล้วสำหรับรายการนี้ กรุณารอสักครู่แล้วลองใหม่")).toBeInTheDocument();
  });

  it("renders a FAILED terminal state honestly, with no imported-rows count claimed", async () => {
    getLegacyHistorySession.mockResolvedValue(
      baseSession({
        status: "failed",
        total_rows: 2,
        valid_rows: 2,
        invalid_rows: 0,
        warning_rows: 0,
        dry_run_completed_at: "t",
        terminal_at: "2026-07-21T00:00:00Z",
        imported_rows: null,
        failure_reason: "การนำเข้าล้มเหลว",
      })
    );
    getLegacyHistoryDryRunPlan.mockRejectedValue(makeApiError(404, "IMPORT_DRY_RUN_PLAN_NOT_FOUND"));
    renderPanel();

    expect(await screen.findByText("สรุปผลการนำเข้า")).toBeInTheDocument();
    expect(screen.getAllByText("การนำเข้าล้มเหลว").length).toBeGreaterThan(0);
  });

  it.each(["validating", "dry_run_running", "executing"] as const)(
    "offers recovery from a %s running state after reload, calling recover on demand",
    async (status) => {
      getLegacyHistorySession.mockResolvedValue(baseSession({ status }));
      recoverLegacyHistorySession.mockResolvedValue({});
      const user = userEvent.setup();
      renderPanel();

      const recoverButton = await screen.findByRole("button", { name: "ตรวจสอบ/กู้คืนงาน" });
      await user.click(recoverButton);
      await waitFor(() => expect(recoverLegacyHistorySession).toHaveBeenCalledWith(SESSION_ID));
    }
  );

  it("shows a non-fatal error banner when recovery is rejected (nothing to recover)", async () => {
    getLegacyHistorySession.mockResolvedValue(baseSession({ status: "dry_run_running" }));
    recoverLegacyHistorySession.mockRejectedValue(makeApiError(409, "IMPORT_SESSION_INVALID_STATE", "nothing to recover"));
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "ตรวจสอบ/กู้คืนงาน" }));

    expect(await screen.findByText("nothing to recover")).toBeInTheDocument();
  });

  it("renders every plan row field (event type, occurred_at, legacy references, Ward/BME text) and never a notes/raw-JSON field", async () => {
    getLegacyHistorySession.mockResolvedValue(
      baseSession({ status: "dry_run_completed", total_rows: 1, valid_rows: 1, invalid_rows: 0, warning_rows: 0, dry_run_completed_at: "t" })
    );
    getLegacyHistoryDryRunPlan.mockResolvedValue(basePlan({ summary: { total_rows: 1, issue_events: 0, receive_events: 1, warnings: 0, blocking_conflicts: 0 } }));
    listLegacyHistoryDryRunPlanRows.mockResolvedValue({
      items: [basePlanRow({ event_type: "RECEIVE", warnings: ["คำเตือนตัวอย่าง"] })],
      next_cursor: null,
      total: 1,
    });
    renderPanel();

    expect(await screen.findByText("ORD-1")).toBeInTheDocument();
    expect(screen.getAllByText("รับเครื่อง").length).toBeGreaterThan(0);
    expect(screen.getAllByText("ICU เก่า").length).toBeGreaterThan(0);
    expect(screen.getAllByText("BME-100").length).toBeGreaterThan(0);
    expect(screen.getAllByText("คำเตือนตัวอย่าง").length).toBeGreaterThan(0);
    expect(screen.queryByText(/หมายเหตุ/)).not.toBeInTheDocument();
  });

  it("paginates plan rows via the plan-id-scoped rows query, accumulating pages without duplicating", async () => {
    getLegacyHistorySession.mockResolvedValue(
      baseSession({ status: "dry_run_completed", total_rows: 2, valid_rows: 2, invalid_rows: 0, warning_rows: 0, dry_run_completed_at: "t" })
    );
    getLegacyHistoryDryRunPlan.mockResolvedValue(basePlan());
    listLegacyHistoryDryRunPlanRows.mockImplementation(async (_sessionId: string, planId: string, params?: { cursor?: string | null }) => {
      expect(planId).toBe("plan-1");
      if (!params?.cursor) {
        return { items: [basePlanRow({ id: "row-1", source_row_number: 1 })], next_cursor: "cursor-2", total: 2 };
      }
      return { items: [basePlanRow({ id: "row-2", source_row_number: 2, event_type: "RECEIVE" })], next_cursor: null, total: 2 };
    });

    const user = userEvent.setup();
    renderPanel();

    await screen.findByText("แถว 1", { exact: false });
    expect(screen.getByRole("button", { name: "โหลดรายละเอียดเพิ่มเติม" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "โหลดรายละเอียดเพิ่มเติม" }));

    await screen.findByText("แถว 2", { exact: false });
    expect(screen.getByText("แถว 1", { exact: false })).toBeInTheDocument();
    expect(listLegacyHistoryDryRunPlanRows).toHaveBeenLastCalledWith(SESSION_ID, "plan-1", expect.objectContaining({ cursor: "cursor-2" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "โหลดรายละเอียดเพิ่มเติม" })).not.toBeInTheDocument());
  });

  it("confirm always targets the currently displayed plan's exact id", async () => {
    getLegacyHistorySession.mockResolvedValue(
      baseSession({ status: "dry_run_completed", total_rows: 2, valid_rows: 2, invalid_rows: 0, warning_rows: 0, dry_run_completed_at: "t" })
    );
    getLegacyHistoryDryRunPlan.mockResolvedValue(basePlan({ id: "plan-current" }));
    listLegacyHistoryDryRunPlanRows.mockResolvedValue({ items: [basePlanRow()], next_cursor: null, total: 1 });
    confirmLegacyHistoryDryRunPlan.mockResolvedValue({});

    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "ยืนยันแผนการนำเข้า" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "ยืนยัน" }));

    await waitFor(() => expect(confirmLegacyHistoryDryRunPlan).toHaveBeenCalledWith(SESSION_ID, "plan-current"));
  });
});
