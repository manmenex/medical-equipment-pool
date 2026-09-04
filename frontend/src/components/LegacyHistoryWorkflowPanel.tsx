import { useState } from "react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";

import { LegacyHistoryDryRunPlanSummary } from "@/components/LegacyHistoryDryRunPlanSummary";
import { LegacyHistoryExecuteAction } from "@/components/LegacyHistoryExecuteAction";
import { LegacyHistoryPlanRowsTable } from "@/components/LegacyHistoryPlanRowsTable";
import { LegacyImportIssuesTable } from "@/components/LegacyImportIssuesTable";
import { LegacyImportResultSummary } from "@/components/LegacyImportResultSummary";
import { LegacyImportStatusBadge } from "@/components/LegacyImportStatusBadge";
import { LegacyImportValidationSummary } from "@/components/LegacyImportValidationSummary";
import {
  confirmLegacyHistoryDryRunPlan,
  dryRunLegacyHistorySession,
  executeLegacyHistorySession,
  getLegacyHistoryDryRunPlan,
  getLegacyHistorySession,
  listLegacyHistoryDryRunPlanRows,
  listLegacyHistoryValidationFindings,
  recoverLegacyHistorySession,
  validateLegacyHistorySession,
} from "@/services/legacyHistoryImportClient";
import type { ImportSessionStatus } from "@/types/legacyImportApi";
import {
  describeLegacyHistoryImportError,
  requiresFreshDryRun,
  type LegacyHistoryImportErrorInfo,
} from "@/utils/legacyImportApiErrors";
import { toImportFinding, toResultSummary } from "@/utils/legacyImportApiMappers";
import { formatDateTimeInTimezone } from "@/utils/printFormat";

// Roadmap PR21E: admission sets mirror the backend's own admission checks
// exactly (never invented client-side) -- these gate which action buttons
// this panel offers, never whether the action itself is allowed, which the
// backend always re-checks and remains the sole authority for. Identical
// to EquipmentMasterWorkflowPanel's own sets: validate/dry-run/execute
// admission is generic PR19 session-lifecycle infrastructure, shared by
// every dataset_type, not something the PR21 adapter changes.
const VALIDATE_ADMISSIBLE_STATUSES = new Set<ImportSessionStatus>(["created", "validated", "validation_failed"]);
const DRY_RUN_ADMISSIBLE_STATUSES = new Set<ImportSessionStatus>(["validated", "dry_run_completed", "dry_run_failed"]);
const EXECUTE_ADMISSIBLE_STATUSES = new Set<ImportSessionStatus>(["dry_run_completed"]);
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
  info: LegacyHistoryImportErrorInfo;
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

// Roadmap PR21E: the interactive Legacy Transaction History real-workflow
// panel -- every action here calls the actual merged PR19/PR20/PR21E0
// backend routes through services/legacyHistoryImportClient.ts and renders
// exactly what the backend returns. No parsing, pairing, Ward/BME
// resolution, event classification, or stale-plan decision is ever made in
// this file; every one of those is read from the backend response and
// displayed as-is. Migration authority approval is handled entirely on the
// create page (pages/LegacyImportCreatePage.tsx) before a session ever
// reaches this panel -- this panel's own dry-run button simply calls the
// backend, which independently re-checks authority itself and reports a
// generic dry_run_failed (surfaced via session.failure_reason below, the
// same honest presentation EquipmentMasterWorkflowPanel already uses for
// every other adapter-raised dry-run failure) if it was never approved.
export function LegacyHistoryWorkflowPanel({ sessionId }: { sessionId: string }) {
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState<LegacyHistoryImportErrorInfo | null>(null);
  const [validating, setValidating] = useState(false);
  const [dryRunning, setDryRunning] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [recovering, setRecovering] = useState(false);

  const sessionQueryKey = ["legacy-import", "legacy-history", "session", sessionId];
  const planQueryKey = ["legacy-import", "legacy-history", "dry-run-plan", sessionId];
  const rowsQueryKeyPrefix = ["legacy-import", "legacy-history", "dry-run-plan-rows", sessionId];
  const findingsQueryKey = ["legacy-import", "legacy-history", "findings", sessionId];

  const {
    data: session,
    isLoading: sessionLoading,
    isError: sessionIsError,
    refetch: refetchSession,
  } = useQuery({
    queryKey: sessionQueryKey,
    queryFn: () => getLegacyHistorySession(sessionId),
    enabled: Boolean(sessionId),
    retry: false,
    refetchInterval: (query) => (query.state.data && POLLING_STATUSES.has(query.state.data.status) ? 3000 : false),
  });

  const shouldFetchPlan = Boolean(session && PLAN_FETCH_STATUSES.has(session.status));
  const {
    data: plan,
    isLoading: planLoading,
    isError: planIsError,
    error: planError,
    refetch: refetchPlan,
  } = useQuery({
    queryKey: planQueryKey,
    queryFn: () => getLegacyHistoryDryRunPlan(sessionId),
    enabled: shouldFetchPlan,
    retry: false,
  });
  const planNotFound = planIsError && describeLegacyHistoryImportError(planError).kind === "plan_not_found";

  // §14 of the PR21E0 task: unlike Equipment Master's `.../dry-run-plan`
  // (which embeds a page of rows in the same resource the identity comes
  // from), PR21's rows endpoint takes an explicit `plan_id` in its own
  // path. Keying this query by `plan?.id` means a dry-run that supersedes
  // the currently displayed plan naturally produces a different query key
  // -- react-query starts a fresh, correctly-scoped rows query for the new
  // plan automatically, rather than requiring the manual cross-plan
  // cursor-mismatch detection EquipmentMasterWorkflowPanel needs for its
  // own single-resource pagination shape.
  const {
    data: rowPages,
    isLoading: rowsLoading,
    isError: rowsIsError,
    fetchNextPage: fetchNextRowsPage,
    hasNextPage: hasNextRowsPage,
    isFetchingNextPage: isFetchingNextRowsPage,
    refetch: refetchRows,
  } = useInfiniteQuery({
    queryKey: [...rowsQueryKeyPrefix, plan?.id],
    queryFn: ({ pageParam }) => listLegacyHistoryDryRunPlanRows(sessionId, (plan as NonNullable<typeof plan>).id, { limit: 50, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    enabled: Boolean(plan) && !planIsError,
    retry: false,
  });
  const rows = rowPages?.pages.flatMap((p) => p.items) ?? [];
  const rowsTotal = rowPages?.pages[0]?.total ?? 0;

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
    queryKey: findingsQueryKey,
    queryFn: ({ pageParam }) => listLegacyHistoryValidationFindings(sessionId, { limit: 50, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    enabled: shouldFetchFindings,
    retry: false,
  });
  const findings = findingPages?.pages.flatMap((p) => p.items) ?? [];
  // Mirrors EquipmentMasterWorkflowPanel's own "findings fetch failure must
  // not look empty" contract: the backend already told us (finding_count >
  // 0) that findings exist -- a failed fetch never silently renders as an
  // empty table, it gates the dry-run button instead until a retry
  // actually succeeds.
  const findingsBlockProgression = shouldFetchFindings && findingsIsError;

  async function refreshAll() {
    await Promise.all([
      refetchSession(),
      queryClient.invalidateQueries({ queryKey: planQueryKey, exact: true }),
      queryClient.invalidateQueries({ queryKey: rowsQueryKeyPrefix }),
      queryClient.invalidateQueries({ queryKey: findingsQueryKey }),
    ]);
  }

  async function handleValidate() {
    setActionError(null);
    setValidating(true);
    try {
      await validateLegacyHistorySession(sessionId);
      await refreshAll();
    } catch (error) {
      setActionError(describeLegacyHistoryImportError(error));
    } finally {
      setValidating(false);
    }
  }

  async function handleDryRun() {
    setActionError(null);
    setDryRunning(true);
    try {
      await dryRunLegacyHistorySession(sessionId);
      await refreshAll();
    } catch (error) {
      setActionError(describeLegacyHistoryImportError(error));
    } finally {
      setDryRunning(false);
    }
  }

  async function handleConfirmPlan() {
    if (!plan) return;
    setActionError(null);
    setConfirming(true);
    try {
      await confirmLegacyHistoryDryRunPlan(sessionId, plan.id);
      await refreshAll();
    } catch (error) {
      setActionError(describeLegacyHistoryImportError(error));
    } finally {
      setConfirming(false);
    }
  }

  async function handleExecute() {
    setActionError(null);
    setExecuting(true);
    try {
      await executeLegacyHistorySession(sessionId);
      await refreshAll();
    } catch (error) {
      setActionError(describeLegacyHistoryImportError(error));
    } finally {
      setExecuting(false);
    }
  }

  async function handleRecover() {
    setActionError(null);
    setRecovering(true);
    try {
      await recoverLegacyHistorySession(sessionId);
      await refreshAll();
    } catch (error) {
      setActionError(describeLegacyHistoryImportError(error));
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
  const validationCounts = session.total_rows !== null
    ? {
        totalRows: session.total_rows,
        validRows: session.valid_rows as number,
        warningRows: session.warning_rows as number,
        invalidRows: session.invalid_rows as number,
      }
    : null;

  return (
    <div className="flex flex-col gap-4">
      <div className="surface rounded-xl border p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h1 className="text-lg font-semibold">นำเข้าประวัติการรับ-ส่งเครื่องมือเดิม</h1>
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

      {validationCounts && !isStructuralFailure && (
        <div className="surface rounded-xl border p-4">
          <LegacyImportValidationSummary counts={validationCounts} findingsByCategory={[]} />
        </div>
      )}

      {shouldFetchFindings && (
        <div className="surface rounded-xl border p-4">
          <h3 className="mb-3 text-sm font-semibold">รายการที่ต้องตรวจสอบ</h3>
          {findingsLoading ? (
            <p className="text-sm text-[var(--text-muted)]">กำลังโหลดรายการ...</p>
          ) : findingsIsError ? (
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

      {plan && !planIsError && (
        <div className="surface rounded-xl border p-4">
          <LegacyHistoryDryRunPlanSummary
            plan={plan}
            onConfirm={handleConfirmPlan}
            confirming={confirming}
            alreadyConfirmed={plan.confirmed_at !== null}
          />

          <div className="mt-4 border-t border-[var(--border)] pt-4">
            <h4 className="mb-3 text-sm font-semibold">รายละเอียดแผนการนำเข้า (รายแถว)</h4>
            {rowsLoading ? (
              <p className="text-sm text-[var(--text-muted)]">กำลังโหลดรายละเอียดแผนการนำเข้า...</p>
            ) : rowsIsError ? (
              <div className="flex flex-col items-start gap-2">
                <p className="text-sm text-status-repair">ไม่สามารถโหลดรายละเอียดแผนการนำเข้าได้</p>
                <button
                  type="button"
                  onClick={() => refetchRows()}
                  className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
                >
                  ลองใหม่
                </button>
              </div>
            ) : (
              <>
                <LegacyHistoryPlanRowsTable rows={rows} />
                {hasNextRowsPage && (
                  <button
                    type="button"
                    onClick={() => fetchNextRowsPage()}
                    disabled={isFetchingNextRowsPage}
                    className="mt-3 rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium disabled:opacity-50"
                  >
                    {isFetchingNextRowsPage ? "กำลังโหลด..." : "โหลดรายละเอียดเพิ่มเติม"}
                  </button>
                )}
                {!hasNextRowsPage && rows.length > 0 && (
                  <p className="mt-2 text-xs text-[var(--text-muted)]">
                    แสดง {rows.length.toLocaleString()} จาก {rowsTotal.toLocaleString()} รายการ
                  </p>
                )}
              </>
            )}
          </div>

          {plan.confirmed_at !== null && EXECUTE_ADMISSIBLE_STATUSES.has(session.status) && (
            <div className="mt-4 border-t border-[var(--border)] pt-4">
              <LegacyHistoryExecuteAction summary={plan.summary} onExecute={handleExecute} executing={executing} />
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
