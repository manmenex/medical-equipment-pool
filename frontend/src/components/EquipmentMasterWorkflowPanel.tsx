import { useState } from "react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";

import { EquipmentMasterDryRunPlanSummary } from "@/components/EquipmentMasterDryRunPlanSummary";
import { EquipmentMasterExecuteAction } from "@/components/EquipmentMasterExecuteAction";
import { EquipmentMasterPlanRowsTable } from "@/components/EquipmentMasterPlanRowsTable";
import { LegacyImportIssuesTable } from "@/components/LegacyImportIssuesTable";
import { LegacyImportResultSummary } from "@/components/LegacyImportResultSummary";
import { LegacyImportStatusBadge } from "@/components/LegacyImportStatusBadge";
import {
  confirmEquipmentMasterDryRunPlan,
  dryRunEquipmentMasterSession,
  executeEquipmentMasterSession,
  getEquipmentMasterDryRunPlan,
  getEquipmentMasterSession,
  listEquipmentMasterValidationFindings,
  recoverEquipmentMasterSession,
  validateEquipmentMasterSession,
} from "@/services/equipmentMasterImportClient";
import type { ImportSessionStatus } from "@/types/legacyImportApi";
import {
  describeEquipmentMasterImportError,
  requiresFreshDryRun,
  type EquipmentMasterImportErrorInfo,
} from "@/utils/legacyImportApiErrors";
import { toImportFinding, toResultSummary } from "@/utils/legacyImportApiMappers";
import { formatDateTimeInTimezone } from "@/utils/printFormat";

// Roadmap PR20F: statuses re-admittable to validate/dry-run, mirroring the
// backend's own admission checks exactly (never invented client-side) --
// backend/app/services/import_validation_service.py's run_validation guard
// (admittable from created/validated/validation_failed) and
// backend/app/services/import_execution_service.py's
// _DRY_RUN_ALLOWED_FROM_STATUSES/_EXECUTE_ALLOWED_FROM_STATUSES constants.
// These gate which action buttons this panel offers -- never whether the
// action itself is allowed, which the backend always re-checks and remains
// the sole authority for.
const VALIDATE_ADMISSIBLE_STATUSES = new Set<ImportSessionStatus>(["created", "validated", "validation_failed"]);
const DRY_RUN_ADMISSIBLE_STATUSES = new Set<ImportSessionStatus>(["validated", "dry_run_completed", "dry_run_failed"]);
const EXECUTE_ADMISSIBLE_STATUSES = new Set<ImportSessionStatus>(["dry_run_completed"]);
// Session-level phases the backend itself will resolve without further
// operator action -- polled at a short interval so this panel reflects the
// backend's own transition the moment it lands, rather than requiring a
// manual reload (design §28: refresh from backend after every transition).
const POLLING_STATUSES = new Set<ImportSessionStatus>(["validating", "dry_run_running", "executing"]);
const PLAN_FETCH_STATUSES = new Set<ImportSessionStatus>([
  "dry_run_completed",
  "dry_run_failed",
  "executing",
  "completed",
  "failed",
  "cancelled",
]);
const RESULT_STATUSES = new Set<ImportSessionStatus>(["completed", "failed", "cancelled"]);

function ErrorBanner({
  info,
  onDismiss,
  onRecover,
}: {
  info: EquipmentMasterImportErrorInfo;
  onDismiss: () => void;
  onRecover?: () => void;
}) {
  return (
    <div role="alert" className="surface flex flex-col gap-2 rounded-xl border border-status-repair/40 bg-status-repair/5 p-4">
      <p className="text-sm font-medium text-status-repair">{info.message}</p>
      {requiresFreshDryRun(info.kind) && (
        <p className="text-xs text-[var(--text-muted)]">กรุณากดทดลองนำเข้าใหม่อีกครั้งด้านล่างก่อนดำเนินการต่อ</p>
      )}
      <div className="flex gap-2">
        {info.kind === "recovery_required" && onRecover && (
          <button
            type="button"
            onClick={onRecover}
            className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
          >
            กู้คืนสถานะ
          </button>
        )}
        <button type="button" onClick={onDismiss} className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium">
          ปิด
        </button>
      </div>
    </div>
  );
}

// Roadmap PR20F: the interactive Equipment Master real-workflow panel --
// every action here calls the actual merged PR20A-E backend routes through
// services/equipmentMasterImportClient.ts and renders exactly what the
// backend returns. No CREATE/UPDATE classification, identity match, row
// validity, or stale-plan decision is ever made in this file; every one of
// those is read from the backend response and displayed as-is (design §33).
export function EquipmentMasterWorkflowPanel({ sessionId }: { sessionId: string }) {
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState<EquipmentMasterImportErrorInfo | null>(null);
  const [validating, setValidating] = useState(false);
  const [dryRunning, setDryRunning] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [recovering, setRecovering] = useState(false);

  const sessionQueryKey = ["legacy-import", "equipment-master", "session", sessionId];
  const planQueryKey = ["legacy-import", "equipment-master", "dry-run-plan", sessionId];

  const {
    data: session,
    isLoading: sessionLoading,
    isError: sessionIsError,
    refetch: refetchSession,
  } = useQuery({
    queryKey: sessionQueryKey,
    queryFn: () => getEquipmentMasterSession(sessionId),
    enabled: Boolean(sessionId),
    retry: false,
    refetchInterval: (query) => (query.state.data && POLLING_STATUSES.has(query.state.data.status) ? 3000 : false),
  });

  const shouldFetchPlan = Boolean(session && PLAN_FETCH_STATUSES.has(session.status));
  const {
    data: planPages,
    isLoading: planLoading,
    isError: planIsError,
    error: planError,
    fetchNextPage: fetchNextPlanPage,
    hasNextPage: hasNextPlanPage,
    isFetchingNextPage: isFetchingNextPlanPage,
    refetch: refetchPlan,
  } = useInfiniteQuery({
    queryKey: planQueryKey,
    queryFn: ({ pageParam }) => getEquipmentMasterDryRunPlan(sessionId, { limit: 50, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.rows_next_cursor,
    enabled: shouldFetchPlan,
    retry: false,
  });
  // Every page shares the same plan identity/summary/status; only `rows`
  // accumulates across pages (design §16: backend cursor pagination, never
  // a client-computed full fetch).
  //
  // Review round 1 (P1 pagination bug): `rows_next_cursor` must come from
  // the LAST fetched page, not `pages[0]` -- the first page's own cursor
  // stays truthy forever once spread onto the merged object, which kept
  // "โหลดรายละเอียดเพิ่มเติม" visible even after every row had already been
  // loaded. Visibility itself is driven by react-query's own `hasNextPage`
  // below, never by this field directly, but the merged object is kept
  // internally consistent regardless.
  const firstPlanPage = planPages?.pages[0];
  // A pagination cursor identifies a row position, not the DryRunPlan. The
  // backend resolves the session's current active plan independently for
  // every page request, so another dry run can supersede the plan between
  // page fetches. Never combine or confirm pages from different persisted
  // artifacts: fail closed and require a reset from page one instead.
  const planIdentityMismatch = Boolean(
    firstPlanPage && planPages.pages.some((page) => page.id !== firstPlanPage.id),
  );
  const plan = firstPlanPage && !planIdentityMismatch
    ? {
        ...firstPlanPage,
        rows: planPages.pages.flatMap((p) => p.rows),
        rows_next_cursor: planPages.pages[planPages.pages.length - 1].rows_next_cursor,
      }
    : undefined;
  const planNotFound =
    planIsError && describeEquipmentMasterImportError(planError).kind === "plan_not_found";

  const shouldFetchFindings = Boolean(session && session.finding_count > 0);
  const {
    data: findingPages,
    isLoading: findingsLoading,
    isError: findingsIsError,
    fetchNextPage: fetchNextFindingsPage,
    hasNextPage: hasNextFindingsPage,
    isFetchingNextPage: isFetchingNextFindingsPage,
    refetch: refetchFindings,
  } = useInfiniteQuery({
    queryKey: ["legacy-import", "equipment-master", "findings", sessionId],
    queryFn: ({ pageParam }) => listEquipmentMasterValidationFindings(sessionId, { limit: 50, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    enabled: shouldFetchFindings,
    retry: false,
  });
  const findings = findingPages?.pages.flatMap((p) => p.items) ?? [];
  // Review round 1 (P2 "Findings request failure must not look empty"): the
  // backend already told us (finding_count > 0) that findings exist for
  // this session -- if the request for them then fails, rendering an empty
  // table would falsely read as "no issues" and could let the operator
  // proceed without ever seeing what the backend flagged. This never
  // substitutes an empty array; it gates progression instead (see the
  // dry-run button below), until a retry actually succeeds.
  const findingsBlockProgression = shouldFetchFindings && findingsIsError;

  async function refreshAll() {
    await Promise.all([
      refetchSession(),
      queryClient.invalidateQueries({ queryKey: ["legacy-import", "equipment-master", "dry-run-plan", sessionId] }),
      queryClient.invalidateQueries({ queryKey: ["legacy-import", "equipment-master", "findings", sessionId] }),
    ]);
  }

  async function refreshPlanFromFirstPage() {
    setActionError(null);
    await queryClient.resetQueries({ queryKey: planQueryKey, exact: true });
  }

  async function handleValidate() {
    setActionError(null);
    setValidating(true);
    try {
      await validateEquipmentMasterSession(sessionId);
      await refreshAll();
    } catch (error) {
      setActionError(describeEquipmentMasterImportError(error));
    } finally {
      setValidating(false);
    }
  }

  async function handleDryRun() {
    setActionError(null);
    setDryRunning(true);
    try {
      await dryRunEquipmentMasterSession(sessionId);
      await refreshAll();
    } catch (error) {
      setActionError(describeEquipmentMasterImportError(error));
    } finally {
      setDryRunning(false);
    }
  }

  async function handleConfirmPlan() {
    if (!plan) return;
    setActionError(null);
    setConfirming(true);
    try {
      // Exact persisted plan identity (design §14) -- never "the latest
      // plan": `plan.id` here is the id already displayed to and reviewed
      // by the operator via the GET above.
      await confirmEquipmentMasterDryRunPlan(sessionId, plan.id);
      await refreshAll();
    } catch (error) {
      setActionError(describeEquipmentMasterImportError(error));
    } finally {
      setConfirming(false);
    }
  }

  async function handleExecute() {
    setActionError(null);
    setExecuting(true);
    try {
      await executeEquipmentMasterSession(sessionId);
      await refreshAll();
    } catch (error) {
      setActionError(describeEquipmentMasterImportError(error));
    } finally {
      setExecuting(false);
    }
  }

  async function handleRecover() {
    setActionError(null);
    setRecovering(true);
    try {
      await recoverEquipmentMasterSession(sessionId);
      await refreshAll();
    } catch (error) {
      setActionError(describeEquipmentMasterImportError(error));
    } finally {
      setRecovering(false);
    }
  }

  if (sessionLoading) {
    return <p className="text-sm text-[var(--text-muted)]">กำลังโหลดรายละเอียดการนำเข้าข้อมูล...</p>;
  }

  if (sessionIsError || !session) {
    return (
      <div className="surface flex flex-col items-start gap-2 rounded-xl border p-4">
        <p className="text-sm text-status-repair">ไม่สามารถโหลดรายละเอียดการนำเข้าข้อมูลได้</p>
        <button
          type="button"
          onClick={() => refetchSession()}
          className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
        >
          ลองใหม่
        </button>
      </div>
    );
  }

  const resultSummary = toResultSummary(session);
  const isStructuralFailure =
    (session.status === "validation_failed" || session.status === "dry_run_failed") &&
    session.total_rows === null &&
    session.finding_count === 0;

  return (
    <div className="flex flex-col gap-4">
      <div className="surface rounded-xl border p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h1 className="text-lg font-semibold">นำเข้าข้อมูลหลักเครื่องมือ</h1>
            <p className="text-sm text-[var(--text-muted)]">เลขอ้างอิงรายการ: {session.id}</p>
          </div>
          <LegacyImportStatusBadge status={session.status} />
        </div>
        <dl className="mt-3 grid grid-cols-1 gap-2 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-xs text-[var(--text-muted)]">วันที่สร้าง</dt>
            <dd>{formatDateTimeInTimezone(session.created_at, "Asia/Bangkok")}</dd>
          </div>
          <div>
            <dt className="text-xs text-[var(--text-muted)]">ตรวจสอบล่าสุด</dt>
            <dd>{session.validated_at ? formatDateTimeInTimezone(session.validated_at, "Asia/Bangkok") : "-"}</dd>
          </div>
          <div>
            <dt className="text-xs text-[var(--text-muted)]">ทดลองนำเข้าล่าสุด</dt>
            <dd>{session.dry_run_completed_at ? formatDateTimeInTimezone(session.dry_run_completed_at, "Asia/Bangkok") : "-"}</dd>
          </div>
        </dl>
        {session.failure_reason && !isStructuralFailure && (
          <p className="mt-3 text-sm text-status-repair">{session.failure_reason}</p>
        )}

        <div className="mt-4 flex flex-wrap gap-2">
          {VALIDATE_ADMISSIBLE_STATUSES.has(session.status) && (
            <button
              type="button"
              onClick={handleValidate}
              disabled={validating}
              className="rounded-lg bg-status-borrowed px-4 py-2.5 text-sm font-medium text-white disabled:opacity-50"
            >
              {validating ? "กำลังตรวจสอบ..." : session.status === "created" ? "ตรวจสอบข้อมูล" : "ตรวจสอบข้อมูลอีกครั้ง"}
            </button>
          )}
          {DRY_RUN_ADMISSIBLE_STATUSES.has(session.status) && (
            <button
              type="button"
              onClick={handleDryRun}
              disabled={dryRunning || findingsBlockProgression}
              className="rounded-lg border border-[var(--border)] px-4 py-2.5 text-sm font-medium disabled:opacity-50"
            >
              {dryRunning ? "กำลังทดลองนำเข้า..." : session.status === "validated" ? "ทดลองนำเข้า" : "ทดลองนำเข้าอีกครั้ง"}
            </button>
          )}
        </div>
        {findingsBlockProgression && DRY_RUN_ADMISSIBLE_STATUSES.has(session.status) && (
          <p className="mt-2 text-xs text-status-repair">
            ต้องโหลดรายการที่ต้องตรวจสอบให้สำเร็จก่อนจึงจะทดลองนำเข้าต่อได้ (ดูด้านล่าง)
          </p>
        )}
        {POLLING_STATUSES.has(session.status) && (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <p role="status" aria-live="polite" className="text-xs text-[var(--text-muted)]">
              กำลังดำเนินการอยู่ กรุณารอสักครู่...
            </p>
            {/* Review round 1 (P1 "Recovery must be reachable from running
                states after reload"): a worker crash, tab close, or lost
                connection can leave the session showing a running status
                with no local error to hang a recover button off of --
                reloading straight into this state must still let the
                operator attempt recovery, without the frontend guessing
                lease staleness itself. The backend is the sole authority:
                it either recovers a genuinely stale job or rejects this as
                IMPORT_SESSION_INVALID_STATE ("nothing to recover, lease
                still active"), which renders as a normal, non-fatal error
                banner below -- never treated as a workflow failure. */}
            <button
              type="button"
              onClick={handleRecover}
              disabled={recovering}
              className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs font-medium disabled:opacity-50"
            >
              {recovering ? "กำลังตรวจสอบ..." : "ตรวจสอบ/กู้คืนงาน"}
            </button>
          </div>
        )}
      </div>

      {actionError && (
        <ErrorBanner info={actionError} onDismiss={() => setActionError(null)} onRecover={recovering ? undefined : handleRecover} />
      )}

      {isStructuralFailure && (
        <div className="surface rounded-xl border border-status-repair/40 bg-status-repair/5 p-4">
          <p className="text-sm font-medium text-status-repair">การตรวจสอบข้อมูลล้มเหลว</p>
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            {session.failure_reason ?? "ไม่สามารถประมวลผลไฟล์นี้ได้ ยังไม่มีผลการตรวจสอบรายแถวสำหรับความพยายามนี้"}
          </p>
        </div>
      )}

      {session.total_rows !== null && !isStructuralFailure && (
        <div className="surface rounded-xl border p-4">
          <h3 className="mb-3 text-sm font-semibold">สรุปผลการตรวจสอบข้อมูล</h3>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { label: "ทั้งหมด", value: session.total_rows, accent: "text-[var(--text-primary,inherit)]" },
              { label: "รายการที่ถูกต้อง", value: session.valid_rows, accent: "text-status-available" },
              { label: "รายการที่มีคำเตือน", value: session.warning_rows, accent: "text-status-pm" },
              { label: "รายการที่ไม่ถูกต้อง", value: session.invalid_rows, accent: "text-status-repair" },
            ].map((card) => (
              <div key={card.label} className="surface flex flex-col gap-1 rounded-xl border p-3">
                <span className="text-xs text-[var(--text-muted)]">{card.label}</span>
                <span className={`text-xl font-semibold ${card.accent}`}>{(card.value ?? 0).toLocaleString()}</span>
              </div>
            ))}
          </div>
          {(session.warning_rows ?? 0) > 0 && (
            <p className="mt-2 text-xs text-[var(--text-muted)]">
              คำเตือนไม่ปิดกั้นการดำเนินการต่อ — สามารถทดลองนำเข้าโดยไม่บันทึกต่อได้แม้มีคำเตือน
            </p>
          )}
        </div>
      )}

      {shouldFetchFindings && (
        <div className="surface rounded-xl border p-4">
          <h3 className="mb-3 text-sm font-semibold">รายการที่ต้องตรวจสอบ</h3>
          {findingsLoading ? (
            <p className="text-sm text-[var(--text-muted)]">กำลังโหลดรายการ...</p>
          ) : findingsIsError ? (
            // Review round 1 (P2): a distinct, explicit failure state --
            // never rendered as if it were a genuine zero-findings result.
            <div role="alert" className="flex flex-col items-start gap-2">
              <p className="text-sm text-status-repair">ไม่สามารถโหลดรายการที่ต้องตรวจสอบได้ (มี {session.finding_count.toLocaleString()} รายการ)</p>
              <button
                type="button"
                onClick={() => refetchFindings()}
                className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
              >
                ลองใหม่
              </button>
            </div>
          ) : (
            <>
              <LegacyImportIssuesTable findings={findings.map(toImportFinding)} />
              {hasNextFindingsPage && (
                <button
                  type="button"
                  onClick={() => fetchNextFindingsPage()}
                  disabled={isFetchingNextFindingsPage}
                  className="mt-3 rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium disabled:opacity-50"
                >
                  {isFetchingNextFindingsPage ? "กำลังโหลด..." : "โหลดเพิ่มเติม"}
                </button>
              )}
            </>
          )}
        </div>
      )}

      {shouldFetchPlan && planLoading && (
        <p className="text-sm text-[var(--text-muted)]">กำลังโหลดแผนการนำเข้า...</p>
      )}

      {shouldFetchPlan && !planLoading && !planNotFound && planIsError && (
        <div className="surface rounded-xl border p-4">
          <p className="text-sm text-status-repair">ไม่สามารถโหลดแผนการนำเข้าได้</p>
          <button
            type="button"
            onClick={() => refetchPlan()}
            className="mt-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
          >
            ลองใหม่
          </button>
        </div>
      )}

      {shouldFetchPlan && planIdentityMismatch && (
        <div role="alert" className="surface rounded-xl border border-status-repair/40 bg-status-repair/5 p-4">
          <p className="text-sm font-medium text-status-repair">แผนการนำเข้ามีการเปลี่ยนแปลงระหว่างโหลดรายละเอียด</p>
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            ระบบจะไม่รวมข้อมูลจากคนละแผน กรุณาโหลดแผนปัจจุบันใหม่ก่อนตรวจสอบและยืนยัน
          </p>
          <button
            type="button"
            onClick={refreshPlanFromFirstPage}
            className="mt-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
          >
            โหลดแผนปัจจุบันใหม่
          </button>
        </div>
      )}

      {plan && !planIsError && (
        <div className="surface rounded-xl border p-4">
          <EquipmentMasterDryRunPlanSummary
            plan={plan}
            onConfirm={handleConfirmPlan}
            confirming={confirming}
            alreadyConfirmed={plan.confirmed_at !== null}
          />

          {/* Review round 1 (P1 "Render the ACTUAL DryRunPlan being
              confirmed"): the operator must see the actual persisted rows
              -- not just aggregate counters -- before confirming/executing.
              `plan.rows` is exactly what the backend returned, accumulated
              page-by-page; nothing here is recomputed. */}
          <div className="mt-4 border-t border-[var(--border)] pt-4">
            <h4 className="mb-3 text-sm font-semibold">รายละเอียดแผนการนำเข้า (รายแถว)</h4>
            <EquipmentMasterPlanRowsTable rows={plan.rows} />
            {/* Review round 1 (P1 pagination bug): visibility is driven by
                react-query's own `hasNextPage` for the CURRENT accumulated
                result, never by a single page's own cursor field. */}
            {hasNextPlanPage && (
              <button
                type="button"
                onClick={() => fetchNextPlanPage()}
                disabled={isFetchingNextPlanPage}
                className="mt-3 rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium disabled:opacity-50"
              >
                {isFetchingNextPlanPage ? "กำลังโหลด..." : "โหลดรายละเอียดเพิ่มเติม"}
              </button>
            )}
            {!hasNextPlanPage && plan.rows.length > 0 && (
              <p className="mt-2 text-xs text-[var(--text-muted)]">
                แสดง {plan.rows.length.toLocaleString()} จาก {plan.rows_total.toLocaleString()} รายการ
              </p>
            )}
          </div>

          {plan.confirmed_at !== null && EXECUTE_ADMISSIBLE_STATUSES.has(session.status) && (
            <div className="mt-4 border-t border-[var(--border)] pt-4">
              <EquipmentMasterExecuteAction summary={plan.summary} onExecute={handleExecute} executing={executing} />
            </div>
          )}
        </div>
      )}

      {resultSummary && RESULT_STATUSES.has(session.status) && (
        <div className="surface rounded-xl border p-4">
          <LegacyImportResultSummary result={resultSummary} />
        </div>
      )}
    </div>
  );
}
