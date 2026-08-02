import { useInfiniteQuery } from "@tanstack/react-query";
import { useLocation } from "react-router-dom";

import { ReportFilterBar } from "@/components/ReportFilterBar";
import { ReportResultsTable } from "@/components/ReportResultsTable";
import { useAppliedReportFilters } from "@/hooks/useAppliedReportFilters";
import { apiErrorMessage } from "@/services/api";
import { getIssueReport } from "@/services/reports";

// Roadmap PR17 Slice 3 (docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md §6.2/
// §7.2/§12): on-screen Issue Report -- what equipment left the pool, to
// which ward, and when. Consumes GET /reports/issue only (never GET
// /transactions). The backend includes both OPEN and CLOSED transactions
// here (§7.2) -- this page never filters out an OPEN (not-yet-received)
// row; a dispatch is a fact about the past regardless of receipt status.
export function IssueReportPage() {
  const appliedFilters = useAppliedReportFilters();
  const queryKey = ["reports", "issue", appliedFilters];
  const location = useLocation();

  const {
    data: pages,
    isLoading,
    isError,
    error,
    refetch,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam }) => getIssueReport({ ...appliedFilters, limit: 25, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
  });

  // Cursor pages are appended in exactly the order the backend returned
  // them -- never re-sorted, reversed, or merged by any client-side key.
  const rows = pages?.pages.flatMap((p) => p.items) ?? [];
  const total = pages?.pages[0]?.total;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">รายงานการเบิก</h1>
          <p className="text-sm text-[var(--text-muted)]">
            รายการเครื่องมือที่เบิกออกจาก Pool ตามช่วงวันที่ทำการและตัวกรองที่เลือก
          </p>
        </div>
        {/* Roadmap PR18C: opens the dedicated print view in a new tab,
            carrying this page's currently applied URL filters over
            verbatim -- the print view never re-derives them. */}
        <a
          href={`/reports/issue-report/print${location.search}`}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
        >
          พิมพ์รายงาน
        </a>
      </div>

      <ReportFilterBar />

      <div className="surface rounded-xl border p-4">
        {isLoading && <p className="text-sm text-[var(--text-muted)]">กำลังโหลดรายงานการเบิก...</p>}
        {isError && (
          <div className="flex flex-col items-start gap-2">
            <p className="text-sm text-status-repair">{apiErrorMessage(error, "ไม่สามารถโหลดรายงานการเบิกได้")}</p>
            <button
              type="button"
              onClick={() => refetch()}
              className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
            >
              ลองใหม่
            </button>
          </div>
        )}
        {!isLoading && !isError && (
          <>
            {typeof total === "number" && (
              <p className="mb-2 text-xs text-[var(--text-muted)]">พบทั้งหมด {total} รายการ</p>
            )}
            <ReportResultsTable rows={rows} />
            {hasNextPage && (
              <button
                type="button"
                onClick={() => fetchNextPage()}
                disabled={isFetchingNextPage}
                className="mt-3 w-full rounded-lg border border-[var(--border)] py-2.5 text-sm font-medium disabled:opacity-60"
              >
                {isFetchingNextPage ? "กำลังโหลด..." : "โหลดเพิ่มเติม"}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
