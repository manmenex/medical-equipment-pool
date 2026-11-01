import { useInfiniteQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { canReviewCutoverReadiness, useAuth } from "@/hooks/useAuth";
import { apiErrorMessage } from "@/services/api";
import { cutoverReadinessKeys, fetchCutoverReadinessRuns } from "@/services/cutoverReadiness";
import { CUTOVER_RUN_STATUS_COLORS, CUTOVER_RUN_STATUS_LABELS } from "@/utils/cutoverReadinessLabels";
import { formatDateTimeInTimezone } from "@/utils/printFormat";

// Roadmap PR23E -- the run list screen for the already-merged PR23B-D
// cutover readiness backend (GET /cutover-readiness-runs). Read-only for
// every authenticated role (mirrors backend VIEW_AND_REPORT_ROLES
// exactly, see hooks/useAuth.ts's canReviewCutoverReadiness) -- this page
// never creates or completes a run; run creation/completion has no
// merged frontend contract in this PR's scope (§36 of the task).
export function CutoverReadinessListPage() {
  const { user } = useAuth();
  const enabled = canReviewCutoverReadiness(user);

  const { data, isLoading, isError, error, refetch, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useInfiniteQuery({
      queryKey: cutoverReadinessKeys.runs({ limit: 25 }),
      queryFn: ({ pageParam }) => fetchCutoverReadinessRuns({ limit: 25, cursor: pageParam }),
      initialPageParam: null as string | null,
      getNextPageParam: (lastPage) => lastPage.next_cursor,
      enabled,
    });

  const runs = data?.pages.flatMap((p) => p.items) ?? [];
  const total = data?.pages[0]?.total ?? null;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-lg font-semibold">ความพร้อมก่อนเปลี่ยนระบบ</h1>
        <p className="text-sm text-[var(--text-muted)]">
          รายการรอบตรวจสอบความพร้อมก่อนเปลี่ยนระบบ (Cutover Readiness) และผลการอนุมัติ
        </p>
      </div>

      <div className="surface rounded-xl border p-4">
        {isLoading && <p className="text-sm text-[var(--text-muted)]">กำลังโหลดรายการ...</p>}
        {isError && (
          <div className="flex flex-col items-start gap-2">
            <p className="text-sm text-status-repair">{apiErrorMessage(error, "ไม่สามารถโหลดรายการความพร้อมก่อนเปลี่ยนระบบได้")}</p>
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
          <p className="text-sm text-[var(--text-muted)]">ยังไม่มีรอบตรวจสอบความพร้อม</p>
        )}
        {!isLoading && !isError && runs.length > 0 && (
          <ul className="flex flex-col gap-3">
            {runs.map((run) => (
              <li key={run.id}>
                <Link
                  to={`/cutover-readiness/${run.id}`}
                  className="surface flex flex-col gap-2 rounded-xl border p-3 transition hover:border-status-borrowed"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">
                      {formatDateTimeInTimezone(run.cutover_instant, "Asia/Bangkok")}
                    </span>
                    <span
                      className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${CUTOVER_RUN_STATUS_COLORS[run.status]}`}
                    >
                      {CUTOVER_RUN_STATUS_LABELS[run.status]}
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--text-muted)]">
                    <span>รหัสรุ่นระบบ: {run.application_baseline_sha.slice(0, 8)}</span>
                    <span>สร้างเมื่อ: {formatDateTimeInTimezone(run.created_at, "Asia/Bangkok")}</span>
                  </div>
                  {run.supersedes_run_id && (
                    <span className="w-fit rounded-full bg-status-out_of_service/15 px-2.5 py-1 text-xs font-medium text-status-out_of_service">
                      แทนที่รอบก่อนหน้า
                    </span>
                  )}
                </Link>
              </li>
            ))}
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
