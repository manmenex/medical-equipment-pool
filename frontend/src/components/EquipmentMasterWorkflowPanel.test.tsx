import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EquipmentMasterWorkflowPanel } from "@/components/EquipmentMasterWorkflowPanel";
import type { DryRunPlanOut, DryRunPlanRowOut, ImportSessionStatus, ImportSessionSummaryOut } from "@/types/legacyImportApi";

const getEquipmentMasterSession = vi.fn();
const getEquipmentMasterDryRunPlan = vi.fn();
const listEquipmentMasterValidationFindings = vi.fn();
const validateEquipmentMasterSession = vi.fn();
const dryRunEquipmentMasterSession = vi.fn();
const confirmEquipmentMasterDryRunPlan = vi.fn();
const executeEquipmentMasterSession = vi.fn();
const recoverEquipmentMasterSession = vi.fn();

vi.mock("@/services/equipmentMasterImportClient", () => ({
  getEquipmentMasterSession: (...args: unknown[]) => getEquipmentMasterSession(...args),
  getEquipmentMasterDryRunPlan: (...args: unknown[]) => getEquipmentMasterDryRunPlan(...args),
  listEquipmentMasterValidationFindings: (...args: unknown[]) => listEquipmentMasterValidationFindings(...args),
  validateEquipmentMasterSession: (...args: unknown[]) => validateEquipmentMasterSession(...args),
  dryRunEquipmentMasterSession: (...args: unknown[]) => dryRunEquipmentMasterSession(...args),
  confirmEquipmentMasterDryRunPlan: (...args: unknown[]) => confirmEquipmentMasterDryRunPlan(...args),
  executeEquipmentMasterSession: (...args: unknown[]) => executeEquipmentMasterSession(...args),
  recoverEquipmentMasterSession: (...args: unknown[]) => recoverEquipmentMasterSession(...args),
}));

const SESSION_ID = "11111111-1111-4111-8111-111111111111";

function baseSession(overrides: Partial<ImportSessionSummaryOut> = {}): ImportSessionSummaryOut {
  return {
    id: SESSION_ID,
    dataset_type: "equipment_master",
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

function basePlan(overrides: Partial<DryRunPlanOut> = {}): DryRunPlanOut {
  return {
    id: "plan-1",
    import_session_id: SESSION_ID,
    import_source_id: "source-1",
    status: "current",
    is_current: true,
    created_at: "2026-07-20T03:30:00Z",
    confirmed_at: null,
    confirmed_by_user_id: null,
    summary: { total_rows: 100, creates: 60, updates: 30, skips: 10, warnings: 2, blocking_conflicts: 0 },
    rows: [],
    rows_next_cursor: null,
    rows_total: 100,
    ...overrides,
  };
}

function basePlanRow(overrides: Partial<DryRunPlanRowOut> = {}): DryRunPlanRowOut {
  return {
    id: "row-1",
    source_row_number: 2,
    action: "CREATE",
    target_equipment_id: null,
    normalized_values: {
      bcm_code: "BCM-001",
      item_no: "ITEM-1",
      equipment_name: "เครื่องช่วยหายใจ",
      brand: "Acme",
    },
    matched_identity_fields: { bcm_code: "BCM-001", item_no: "ITEM-1" },
    expected_equipment_version: 7,
    warnings: null,
    ...overrides,
  };
}

function emptyFindingsPage() {
  return { items: [], next_cursor: null, total: 0 };
}

function makeApiError(status: number, code: string, detail = "error") {
  return { isAxiosError: true, response: { status, data: { code, detail, status } } };
}

function planNotFoundError() {
  return makeApiError(404, "IMPORT_DRY_RUN_PLAN_NOT_FOUND", "no plan yet");
}

afterEach(() => {
  vi.resetAllMocks();
});

function renderPanel(sessionId = SESSION_ID) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <EquipmentMasterWorkflowPanel sessionId={sessionId} />
    </QueryClientProvider>
  );
}

describe("EquipmentMasterWorkflowPanel", () => {
  // Roadmap PR20F design §41 "successful frontend flow test": every step
  // below is driven by the mocked HTTP boundary only (services/
  // equipmentMasterImportClient.ts) -- no business logic (row
  // classification, validity, plan identity) is computed in this test or
  // in the component; each transition renders exactly what the "backend"
  // mock returns.
  it("drives validate -> dry-run -> confirm exact plan -> execute, calling the real endpoints and rendering the backend's own persisted state at every step", async () => {
    let session = baseSession();
    let plan: DryRunPlanOut | null = null;

    getEquipmentMasterSession.mockImplementation(async () => session);
    listEquipmentMasterValidationFindings.mockResolvedValue(emptyFindingsPage());
    getEquipmentMasterDryRunPlan.mockImplementation(async () => {
      if (!plan) throw planNotFoundError();
      return plan;
    });
    validateEquipmentMasterSession.mockImplementation(async () => {
      session = baseSession({
        status: "validated",
        validated_at: "2026-07-20T03:10:00Z",
        total_rows: 100,
        valid_rows: 98,
        invalid_rows: 0,
        warning_rows: 2,
      });
      return session;
    });
    dryRunEquipmentMasterSession.mockImplementation(async () => {
      session = { ...session, status: "dry_run_completed", dry_run_completed_at: "2026-07-20T03:20:00Z" };
      plan = basePlan();
      return session;
    });
    confirmEquipmentMasterDryRunPlan.mockImplementation(async (sessionIdArg: string, planId: string) => {
      expect(sessionIdArg).toBe(SESSION_ID);
      // Exact persisted plan identity (design §14) -- never "the latest
      // plan" inferred from the session.
      expect(planId).toBe(plan?.id);
      plan = { ...(plan as DryRunPlanOut), confirmed_at: "2026-07-20T03:31:00Z", confirmed_by_user_id: "user-1" };
      return {
        id: plan.id,
        import_session_id: SESSION_ID,
        status: "confirmed",
        confirmed_at: plan.confirmed_at,
        confirmed_by_user_id: plan.confirmed_by_user_id,
        summary: plan.summary,
      };
    });
    executeEquipmentMasterSession.mockImplementation(async () => {
      session = {
        ...session,
        status: "completed",
        executed_at: "2026-07-20T03:40:00Z",
        terminal_at: "2026-07-20T03:40:00Z",
        imported_rows: 90,
      };
      return session;
    });

    const user = userEvent.setup();
    renderPanel();

    expect(await screen.findByText("นำเข้าข้อมูลหลักเครื่องมือ")).toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: "ตรวจสอบข้อมูล" }));
    await waitFor(() => expect(validateEquipmentMasterSession).toHaveBeenCalledWith(SESSION_ID));

    const dryRunButton = await screen.findByRole("button", { name: "ทดลองนำเข้า" });
    await user.click(dryRunButton);
    await waitFor(() => expect(dryRunEquipmentMasterSession).toHaveBeenCalledWith(SESSION_ID));

    await screen.findByText("แผนการนำเข้า (ทดลองนำเข้าโดยยังไม่บันทึก)");
    await user.click(screen.getByRole("button", { name: "ยืนยันแผนการนำเข้า" }));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "ยืนยัน" }));
    await waitFor(() => expect(confirmEquipmentMasterDryRunPlan).toHaveBeenCalledWith(SESSION_ID, "plan-1"));

    await screen.findByText("ยืนยันแผนนี้แล้ว พร้อมดำเนินการนำเข้าจริง");
    const executeButton = await screen.findByRole("button", { name: "ดำเนินการนำเข้าจริง" });
    await user.click(executeButton);
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "ยืนยันดำเนินการ" }));
    await waitFor(() => expect(executeEquipmentMasterSession).toHaveBeenCalledWith(SESSION_ID));

    expect(await screen.findByText("สรุปผลการนำเข้า")).toBeInTheDocument();
    expect(screen.getByText("90")).toBeInTheDocument();
  });

  it("shows backend validation findings, marks warnings as non-blocking, and never offers dry-run before validation resolves blocking errors", async () => {
    getEquipmentMasterSession.mockResolvedValue(
      baseSession({
        status: "validation_failed",
        total_rows: 100,
        valid_rows: 90,
        invalid_rows: 5,
        warning_rows: 5,
        finding_count: 5,
      })
    );
    listEquipmentMasterValidationFindings.mockResolvedValue({
      items: [
        { id: "f1", row_number: 3, field: "asset_number", error_code: "REQUIRED", message: "จำเป็นต้องระบุ", severity: "error" },
        { id: "f2", row_number: 4, field: "notes", error_code: "FORMAT", message: "รูปแบบไม่ถูกต้อง", severity: "warning" },
      ],
      next_cursor: null,
      total: 2,
    });

    renderPanel();

    // Rendered twice -- once in the desktop table, once in the mobile card
    // fallback (LegacyImportIssuesTable's responsive layout); jsdom has no
    // viewport, so both are present in the DOM.
    expect((await screen.findAllByText("จำเป็นต้องระบุ")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("รูปแบบไม่ถูกต้อง").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /ทดลองนำเข้า/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ตรวจสอบข้อมูลอีกครั้ง" })).toBeInTheDocument();
    expect(dryRunEquipmentMasterSession).not.toHaveBeenCalled();
  });

  it("represents a structural validation failure truthfully -- null counters, no fabricated findings, real failure reason", async () => {
    getEquipmentMasterSession.mockResolvedValue(
      baseSession({ status: "validation_failed", failure_reason: "ไม่สามารถอ่านไฟล์ได้ รูปแบบไฟล์ไม่ถูกต้อง" })
    );

    renderPanel();

    expect(await screen.findByText("การตรวจสอบข้อมูลล้มเหลว")).toBeInTheDocument();
    expect(screen.getByText("ไม่สามารถอ่านไฟล์ได้ รูปแบบไฟล์ไม่ถูกต้อง")).toBeInTheDocument();
    expect(screen.queryByText("สรุปผลการตรวจสอบข้อมูล")).not.toBeInTheDocument();
    expect(listEquipmentMasterValidationFindings).not.toHaveBeenCalled();
  });

  it("presents the unified stale-plan contract on confirm without distinguishing the sub-case, and never attempts execute", async () => {
    const session = baseSession({ status: "dry_run_completed", dry_run_completed_at: "2026-07-20T03:20:00Z" });
    getEquipmentMasterSession.mockResolvedValue(session);
    getEquipmentMasterDryRunPlan.mockResolvedValue(basePlan());
    confirmEquipmentMasterDryRunPlan.mockRejectedValue(makeApiError(409, "IMPORT_DRY_RUN_PLAN_STALE"));

    const user = userEvent.setup();
    renderPanel();

    await screen.findByText("แผนการนำเข้า (ทดลองนำเข้าโดยยังไม่บันทึก)");
    await user.click(screen.getByRole("button", { name: "ยืนยันแผนการนำเข้า" }));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "ยืนยัน" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("แผนการนำเข้าที่ตรวจสอบไว้ไม่สามารถใช้งานได้แล้ว");
    expect(screen.getByText(/กรุณากดทดลองนำเข้าใหม่อีกครั้ง/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "ดำเนินการนำเข้าจริง" })).not.toBeInTheDocument();
    expect(executeEquipmentMasterSession).not.toHaveBeenCalled();
  });

  it("shows an execution-time concurrency conflict without ever rendering a success state, and requires a fresh dry-run", async () => {
    getEquipmentMasterSession.mockResolvedValue(baseSession({ status: "dry_run_completed", dry_run_completed_at: "2026-07-20T03:20:00Z" }));
    getEquipmentMasterDryRunPlan.mockResolvedValue(basePlan({ confirmed_at: "2026-07-20T03:31:00Z", confirmed_by_user_id: "user-1" }));
    executeEquipmentMasterSession.mockRejectedValue(makeApiError(500, "IMPORT_EXECUTION_FAILED"));

    const user = userEvent.setup();
    renderPanel();

    const executeButton = await screen.findByRole("button", { name: "ดำเนินการนำเข้าจริง" });
    await user.click(executeButton);
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "ยืนยันดำเนินการ" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("การนำเข้าข้อมูลจริงล้มเหลว");
    expect(screen.queryByText("สรุปผลการนำเข้า")).not.toBeInTheDocument();
    expect(screen.queryByText(/completed/i)).not.toBeInTheDocument();
  });

  it("renders a FAILED terminal result honestly -- never a success card, and never coerces a null imported-row count to zero", async () => {
    getEquipmentMasterSession.mockResolvedValue(
      baseSession({
        status: "failed",
        dry_run_completed_at: "2026-07-20T03:20:00Z",
        executed_at: "2026-07-20T03:40:00Z",
        terminal_at: "2026-07-20T03:40:00Z",
        imported_rows: null,
        failure_reason: "ข้อมูลเครื่องมือมีการเปลี่ยนแปลงหลังทดลองนำเข้า",
      })
    );
    getEquipmentMasterDryRunPlan.mockResolvedValue(basePlan({ confirmed_at: "2026-07-20T03:31:00Z", confirmed_by_user_id: "user-1" }));

    renderPanel();

    expect(await screen.findByText("สรุปผลการนำเข้า")).toBeInTheDocument();
    expect(screen.getByText("การนำเข้าล้มเหลว")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
    expect(screen.queryByText(/^90$/)).not.toBeInTheDocument();
  });

  it("renders a COMPLETED result of exactly zero imported rows as an actual zero, not the null/unknown message", async () => {
    getEquipmentMasterSession.mockResolvedValue(
      baseSession({
        status: "completed",
        dry_run_completed_at: "2026-07-20T03:20:00Z",
        executed_at: "2026-07-20T03:40:00Z",
        terminal_at: "2026-07-20T03:40:00Z",
        imported_rows: 0,
      })
    );
    getEquipmentMasterDryRunPlan.mockResolvedValue(basePlan({ confirmed_at: "2026-07-20T03:31:00Z", confirmed_by_user_id: "user-1" }));

    renderPanel();

    expect(await screen.findByText("สรุปผลการนำเข้า")).toBeInTheDocument();
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.queryByText("ไม่ทราบจำนวนแถวที่นำเข้า")).not.toBeInTheDocument();
  });

  it("offers a recovery action when the backend reports a stuck prior attempt, and calls the recover endpoint", async () => {
    getEquipmentMasterSession.mockResolvedValue(baseSession({ status: "validated", total_rows: 100, valid_rows: 100, invalid_rows: 0, warning_rows: 0 }));
    dryRunEquipmentMasterSession.mockRejectedValue(makeApiError(409, "IMPORT_RECOVERY_REQUIRED"));
    recoverEquipmentMasterSession.mockResolvedValue(baseSession({ status: "validated" }));

    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "ทดลองนำเข้า" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("การดำเนินการก่อนหน้าค้างอยู่");

    await user.click(screen.getByRole("button", { name: "กู้คืนสถานะ" }));
    await waitFor(() => expect(recoverEquipmentMasterSession).toHaveBeenCalledWith(SESSION_ID));
  });

  it("supports backend cursor pagination for validation findings instead of fetching everything at once", async () => {
    getEquipmentMasterSession.mockResolvedValue(
      baseSession({ status: "validation_failed", total_rows: 5000, valid_rows: 4998, invalid_rows: 2, warning_rows: 0, finding_count: 2 })
    );
    listEquipmentMasterValidationFindings.mockImplementation(async (_sessionId: string, params?: { cursor?: string | null }) => {
      if (!params?.cursor) {
        return {
          items: [{ id: "f1", row_number: 1, field: "asset_number", error_code: "REQUIRED", message: "หน้าแรก", severity: "error" }],
          next_cursor: "page-2",
          total: 2,
        };
      }
      return {
        items: [{ id: "f2", row_number: 2, field: "asset_number", error_code: "REQUIRED", message: "หน้าสอง", severity: "error" }],
        next_cursor: null,
        total: 2,
      };
    });

    const user = userEvent.setup();
    renderPanel();

    expect((await screen.findAllByText("หน้าแรก")).length).toBeGreaterThan(0);
    expect(screen.queryByText("หน้าสอง")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "โหลดเพิ่มเติม" }));
    expect((await screen.findAllByText("หน้าสอง")).length).toBeGreaterThan(0);
    expect(listEquipmentMasterValidationFindings).toHaveBeenLastCalledWith(SESSION_ID, expect.objectContaining({ cursor: "page-2" }));
  });

  // Roadmap PR20F review round 1, P1 "Render the ACTUAL DryRunPlan being
  // confirmed": the operator must see the exact persisted artifact, not
  // just aggregate counters.
  describe("DryRunPlan row rendering", () => {
    it("renders the plan ID and created timestamp, never the session ID as a stand-in", async () => {
      getEquipmentMasterSession.mockResolvedValue(baseSession({ status: "dry_run_completed", dry_run_completed_at: "2026-07-20T03:20:00Z" }));
      getEquipmentMasterDryRunPlan.mockResolvedValue(basePlan({ id: "plan-xyz-789", created_at: "2026-07-20T03:30:00Z" }));

      renderPanel();

      expect(await screen.findByText("plan-xyz-789")).toBeInTheDocument();
      expect(screen.getByText("รหัสแผนการนำเข้า")).toBeInTheDocument();
    });

    it("renders the actual persisted plan rows with backend-reported CREATE/UPDATE/SKIP actions, BCM/Item No., target equipment, normalized values, and warnings -- never expected_equipment_version", async () => {
      getEquipmentMasterSession.mockResolvedValue(baseSession({ status: "dry_run_completed", dry_run_completed_at: "2026-07-20T03:20:00Z" }));
      getEquipmentMasterDryRunPlan.mockResolvedValue(
        basePlan({
          rows: [
            basePlanRow({ id: "row-create", source_row_number: 2, action: "CREATE" }),
            basePlanRow({
              id: "row-update",
              source_row_number: 3,
              action: "UPDATE",
              target_equipment_id: "eq-999",
              normalized_values: { equipment_name: "เตียงผู้ป่วย", brand: "MedCo" },
              matched_identity_fields: { bcm_code: "BCM-002" },
              warnings: [{ field: "serial_number", error_code: "MINOR", message: "หมายเลขเครื่องไม่ตรงรูปแบบปกติ", severity: "warning" }],
            }),
            basePlanRow({
              id: "row-skip",
              source_row_number: 4,
              action: "SKIP",
              normalized_values: {},
              matched_identity_fields: {},
              warnings: [{ field: "asset_number", error_code: "ASSET_NUMBER_REQUIRED_FOR_CREATE", message: "ไม่สามารถสร้างใหม่ได้เนื่องจากไม่มีหมายเลขทรัพย์สิน", severity: "error" }],
            }),
          ],
          rows_total: 3,
        })
      );

      renderPanel();

      await screen.findByText("รายละเอียดแผนการนำเข้า (รายแถว)");
      expect(screen.getAllByText("สร้างใหม่").length).toBeGreaterThan(0);
      expect(screen.getAllByText("อัปเดต").length).toBeGreaterThan(0);
      expect(screen.getAllByText("ข้าม").length).toBeGreaterThan(0);
      expect(screen.getAllByText("BCM-001").length).toBeGreaterThan(0);
      expect(screen.getAllByText("BCM-002").length).toBeGreaterThan(0);
      expect(screen.getAllByText("eq-999", { exact: false }).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/เตียงผู้ป่วย/).length).toBeGreaterThan(0);
      expect(screen.getAllByText("หมายเลขเครื่องไม่ตรงรูปแบบปกติ").length).toBeGreaterThan(0);
      expect(screen.getAllByText("ไม่สามารถสร้างใหม่ได้เนื่องจากไม่มีหมายเลขทรัพย์สิน").length).toBeGreaterThan(0);
      // Internal optimistic-concurrency value -- never surfaced to the operator.
      expect(screen.queryByText("7")).not.toBeInTheDocument();
    });
  });

  describe("DryRunPlan row pagination", () => {
    it("shows Load more only while more rows exist, appends without duplicating, and hides the button on the final page", async () => {
      getEquipmentMasterSession.mockResolvedValue(baseSession({ status: "dry_run_completed", dry_run_completed_at: "2026-07-20T03:20:00Z" }));
      // Distinctive, non-summary-colliding row numbers -- the plan summary
      // cards already render digits like "2" (default warnings count), so
      // row numbers are chosen to never collide with any summary value.
      getEquipmentMasterDryRunPlan.mockImplementation(async (_sessionId: string, params?: { cursor?: string | null }) => {
        if (!params?.cursor) {
          return basePlan({ rows: [basePlanRow({ id: "row-501", source_row_number: 501 })], rows_next_cursor: "rows-page-2", rows_total: 2 });
        }
        return basePlan({ rows: [basePlanRow({ id: "row-502", source_row_number: 502 })], rows_next_cursor: null, rows_total: 2 });
      });

      const user = userEvent.setup();
      renderPanel();

      await screen.findByText("รายละเอียดแผนการนำเข้า (รายแถว)");
      expect(screen.getAllByText("501", { exact: false }).length).toBeGreaterThan(0);
      expect(screen.queryByText("502", { exact: false })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "โหลดรายละเอียดเพิ่มเติม" })).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "โหลดรายละเอียดเพิ่มเติม" }));

      // Row 501 remains (accumulated, not discarded) and row 502 is
      // appended -- never duplicated. Each appears once in the desktop
      // table and once in the mobile card fallback.
      await waitFor(() => expect(screen.getAllByText("501", { exact: false })).toHaveLength(2));
      expect(screen.getAllByText("502", { exact: false })).toHaveLength(2);
      expect(screen.queryByRole("button", { name: "โหลดรายละเอียดเพิ่มเติม" })).not.toBeInTheDocument();
      expect(screen.getByText("แสดง 2 จาก 2 รายการ")).toBeInTheDocument();
      expect(getEquipmentMasterDryRunPlan).toHaveBeenLastCalledWith(SESSION_ID, expect.objectContaining({ cursor: "rows-page-2" }));
    });
  });

  it("confirm always targets the current backend plan identity, never a plan superseded by a later dry-run", async () => {
    let session = baseSession({ status: "dry_run_completed", dry_run_completed_at: "2026-07-20T03:20:00Z" });
    let plan = basePlan({ id: "plan-old" });
    getEquipmentMasterSession.mockImplementation(async () => session);
    getEquipmentMasterDryRunPlan.mockImplementation(async () => plan);
    dryRunEquipmentMasterSession.mockImplementation(async () => {
      plan = basePlan({ id: "plan-new" });
      session = { ...session, status: "dry_run_completed", dry_run_completed_at: "2026-07-20T04:00:00Z" };
      return session;
    });
    confirmEquipmentMasterDryRunPlan.mockResolvedValue({
      id: "plan-new",
      import_session_id: SESSION_ID,
      status: "confirmed",
      confirmed_at: "now",
      confirmed_by_user_id: "user-1",
      summary: plan.summary,
    });

    const user = userEvent.setup();
    renderPanel();

    await screen.findByText("plan-old");
    // A later dry-run (e.g. re-run after noticing something) supersedes the
    // plan already on screen.
    await user.click(screen.getByRole("button", { name: "ทดลองนำเข้าอีกครั้ง" }));
    await screen.findByText("plan-new");

    await user.click(screen.getByRole("button", { name: "ยืนยันแผนการนำเข้า" }));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "ยืนยัน" }));

    await waitFor(() => expect(confirmEquipmentMasterDryRunPlan).toHaveBeenCalledWith(SESSION_ID, "plan-new"));
    expect(confirmEquipmentMasterDryRunPlan).not.toHaveBeenCalledWith(SESSION_ID, "plan-old");
  });

  // Roadmap PR20F review round 1, P1 "Recovery must be reachable from
  // running states after reload": a worker crash, tab close, or refresh can
  // land the operator directly on a running status with no prior local
  // error -- recovery must still be reachable, and the frontend never
  // computes lease staleness itself (that stays entirely backend-owned).
  describe.each<ImportSessionStatus>(["validating", "dry_run_running", "executing"])(
    "running-state recovery (%s)",
    (status) => {
      it("offers a recovery action, calls the real recover endpoint, and refetches backend state on success", async () => {
        // "executing" is the one running status that also triggers the
        // plan fetch (PLAN_FETCH_STATUSES) -- mocked here regardless of
        // status so this table-driven test is uniform across all three.
        getEquipmentMasterDryRunPlan.mockResolvedValue(basePlan());
        getEquipmentMasterSession.mockResolvedValueOnce(baseSession({ status }));
        recoverEquipmentMasterSession.mockResolvedValue(baseSession({ status: "validation_failed", failure_reason: "กู้คืนสำเร็จ" }));
        getEquipmentMasterSession.mockResolvedValue(baseSession({ status: "validation_failed", failure_reason: "กู้คืนสำเร็จ" }));

        const user = userEvent.setup();
        renderPanel();

        const recoverButton = await screen.findByRole("button", { name: "ตรวจสอบ/กู้คืนงาน" });
        await user.click(recoverButton);

        await waitFor(() => expect(recoverEquipmentMasterSession).toHaveBeenCalledWith(SESSION_ID));
        expect(await screen.findByText("กู้คืนสำเร็จ")).toBeInTheDocument();
      });
    }
  );

  it("treats a backend rejection of recovery (lease still active) as a non-fatal, non-destructive message, not a workflow failure", async () => {
    getEquipmentMasterDryRunPlan.mockResolvedValue(basePlan());
    getEquipmentMasterSession.mockResolvedValue(baseSession({ status: "executing" }));
    recoverEquipmentMasterSession.mockRejectedValue(
      makeApiError(409, "IMPORT_SESSION_INVALID_STATE", "Nothing to recover: no stale-running job exists for this session.")
    );

    const user = userEvent.setup();
    renderPanel();

    const recoverButton = await screen.findByRole("button", { name: "ตรวจสอบ/กู้คืนงาน" });
    await user.click(recoverButton);

    expect(await screen.findByRole("alert")).toHaveTextContent("Nothing to recover: no stale-running job exists for this session.");
    // Still polling/executing -- the running-state UI (and its recovery
    // action) remains, proving this was not treated as fatal.
    expect(screen.getByRole("button", { name: "ตรวจสอบ/กู้คืนงาน" })).toBeInTheDocument();
    expect(screen.getByText("กำลังดำเนินการอยู่ กรุณารอสักครู่...")).toBeInTheDocument();
  });

  // Roadmap PR20F review round 1, P2 "Findings request failure must not
  // look empty".
  describe("findings request failure vs genuine empty result", () => {
    it("shows an explicit error state (not an empty table) when finding_count > 0 but the findings request fails, and blocks dry-run until retry succeeds", async () => {
      getEquipmentMasterSession.mockResolvedValue(
        baseSession({ status: "validated", total_rows: 100, valid_rows: 95, invalid_rows: 0, warning_rows: 5, finding_count: 5 })
      );
      listEquipmentMasterValidationFindings.mockRejectedValue(new Error("network error"));

      renderPanel();

      expect(await screen.findByRole("alert")).toHaveTextContent("ไม่สามารถโหลดรายการที่ต้องตรวจสอบได้");
      expect(screen.queryByText("ไม่พบรายการที่มีปัญหา")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "ทดลองนำเข้า" })).toBeDisabled();
      expect(screen.getByText(/ต้องโหลดรายการที่ต้องตรวจสอบให้สำเร็จก่อน/)).toBeInTheDocument();
    });

    it("retry calls refetch, and a successful retry renders the actual findings and re-enables dry-run", async () => {
      getEquipmentMasterSession.mockResolvedValue(
        baseSession({ status: "validated", total_rows: 100, valid_rows: 95, invalid_rows: 0, warning_rows: 5, finding_count: 1 })
      );
      listEquipmentMasterValidationFindings.mockRejectedValueOnce(new Error("network error"));
      listEquipmentMasterValidationFindings.mockResolvedValueOnce({
        items: [{ id: "f1", row_number: 3, field: "notes", error_code: "FORMAT", message: "กู้คืนสำเร็จแล้ว", severity: "warning" }],
        next_cursor: null,
        total: 1,
      });

      const user = userEvent.setup();
      renderPanel();

      await screen.findByRole("alert");
      await user.click(screen.getByRole("button", { name: "ลองใหม่" }));

      expect((await screen.findAllByText("กู้คืนสำเร็จแล้ว")).length).toBeGreaterThan(0);
      expect(screen.getByRole("button", { name: "ทดลองนำเข้า" })).toBeEnabled();
    });

    it("renders the genuine empty state (not an error) when the request succeeds with zero findings", async () => {
      getEquipmentMasterSession.mockResolvedValue(
        baseSession({ status: "validated", total_rows: 100, valid_rows: 100, invalid_rows: 0, warning_rows: 0, finding_count: 2 })
      );
      listEquipmentMasterValidationFindings.mockResolvedValue(emptyFindingsPage());

      renderPanel();

      expect(await screen.findByText("ไม่พบรายการที่มีปัญหา")).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "ทดลองนำเข้า" })).toBeEnabled();
    });

    it("shows a loading state distinct from both error and empty while findings are in flight", async () => {
      getEquipmentMasterSession.mockResolvedValue(
        baseSession({ status: "validated", total_rows: 100, valid_rows: 100, invalid_rows: 0, warning_rows: 0, finding_count: 2 })
      );
      listEquipmentMasterValidationFindings.mockReturnValue(new Promise(() => {}));

      renderPanel();

      expect(await screen.findByText("กำลังโหลดรายการ...")).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(screen.queryByText("ไม่พบรายการที่มีปัญหา")).not.toBeInTheDocument();
    });
  });
});
