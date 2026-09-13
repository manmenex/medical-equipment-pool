import { useInfiniteQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { canReviewReconciliation, useAuth } from "@/hooks/useAuth";
import { apiErrorMessage } from "@/services/api";
import { fetchReconciliationRuns, reconciliationKeys } from "@/services/reconciliation";
import {
  RECONCILIATION_RUN_STATUS_COLORS,
  RECONCILIATION_RUN_STATUS_LABELS,
} from "@/utils/reconciliationLabels";
import { formatDateTimeInTimezone } from "@/utils/printFormat";

// Roadmap PR22F -- the run list screen for Roadmap PR22's reconciliation
// review workflow (backend: PR22D's GET /legacy-reconciliation-runs).
// Read-only for every authenticated role (mirrors backend
// VIEW_AND_REPORT_ROLES exactly, see hooks/useAuth.ts's
// canReviewReconciliation) -- this page never creates a run or triggers
// analysis; run creation/execution has no merged frontend contract in
// this PR's scope.
export function ReconciliationListPage() {
  const { user } = useAuth();
  const enabled = canReviewReconciliation(user);

  const { data, isLoading, isError, error, refetch, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useInfiniteQuery({
      queryKey: reconciliationKeys.runs({ limit: 25 }),
      queryFn: ({ pageParam }) => fetchReconciliationRuns({ limit: 25, cursor: pageParam }),
      initialPageParam: null as string | null,
      getNextPageParam: (lastPage) => lastPage.next_cursor,
      enabled,
    });

  const runs = data?.pages.flatMap((p) => p.items) ?? [];
  const total = data?.pages[0]?.total ?? null;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-lg font-semibold">ตรวจสอบข้อมูลย้อนหลัง</h1>
        <p className="text-sm text-[var(--text-muted)]">
          รายการรอบการตรวจสอบข้อมูลเดิม (Legacy Data Reconciliation) และผลการตรวจสอบ
        </p>
      </div>

      <div className="surface rounded-xl border p-4">
        {isLoading && <p className="text-sm text-[var(--text-muted)]">กำลังโหลดรายการตรวจสอบข้อมูล...</p>}
        {isError && (
          <div className="flex flex-col items-start gap-2">
            <p className="text-sm text-status-repair">{apiErrorMessage(error, "ไม่สามารถโหลดรายการตรวจสอบข้อมูลได้")}</p>
            <button
              type="button"
              onClick={() => refetch()}
              className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
            >
              ลองใหม่
            </button>
          </div>
        )}
        {!isLoading && !isError && runs.length === 0 && (
          <p className="text-sm text-[var(--text-muted)]">ยังไม่มีรอบการตรวจสอบข้อมูล</p>
        )}
        {!isLoading && !isError && runs.length > 0 && (
          <ul className="flex flex-col gap-3">
            {runs.map((run) => {
              return (
                <li key={run.id}>
                  <Link
                    to={`/reconciliation/${run.id}`}
                    className="surface flex flex-col gap-2 rounded-xl border p-3 transition hover:border-status-borrowed"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium">
                        {formatDateTimeInTimezone(run.created_at, "Asia/Bangkok")}
                      </span>
                      <span
                        className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${RECONCILIATION_RUN_STATUS_COLORS[run.status]}`}
                      >
                        {RECONCILIATION_RUN_STATUS_LABELS[run.status]}
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--text-muted)]">
                      <span>เวอร์ชันกฎ: {run.rule_version}</span>
                      <span>
                        ช่วงข้อมูลเดิม: {formatDateTimeInTimezone(run.legacy_coverage_start, "Asia/Bangkok")} –{" "}
                        {formatDateTimeInTimezone(run.legacy_coverage_end, "Asia/Bangkok")}
                      </span>
                    </div>
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                      <span>
                        รายการที่ตรวจพบ: <strong>{run.summary_total_findings.toLocaleString()}</strong>
                      </span>
                      {run.has_signoff ? (
                        <span className="inline-flex items-center rounded-full bg-status-available/15 px-2.5 py-1 text-xs font-medium text-status-available">
                          ลงนามยืนยันแล้ว
                        </span>
                      ) : (
                        run.status === "completed" && (
                          <span className="text-xs text-[var(--text-muted)]">ยังไม่ลงนามยืนยัน</span>
                        )
                      )}
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
        {!isLoading && !isError && hasNextPage && (
          <button
            type="button"
            onClick={() => fetchNextPage()}
            disabled={isFetchingNextPage}
            className="mt-3 rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium disabled:opacity-50"
          >
            {isFetchingNextPage ? "กำลังโหลด..." : "โหลดเพิ่มเติม"}
          </button>
        )}
        {!isLoading && !isError && !hasNextPage && total !== null && runs.length > 0 && (
          <p className="mt-2 text-xs text-[var(--text-muted)]">
            แสดง {runs.length.toLocaleString()} จาก {total.toLocaleString()} รายการ
          </p>
        )}
      </div>
    </div>
  );
}
