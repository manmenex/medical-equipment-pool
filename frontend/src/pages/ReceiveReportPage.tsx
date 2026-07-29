import { useInfiniteQuery } from "@tanstack/react-query";

import { ReportFilterBar } from "@/components/ReportFilterBar";
import { ReportResultsTable } from "@/components/ReportResultsTable";
import { useAppliedReportFilters } from "@/hooks/useAppliedReportFilters";
import { apiErrorMessage } from "@/services/api";
import { getReceiveReport } from "@/services/reports";

// Roadmap PR17 Slice 3 (docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md §6.1/
// §7.1/§12): on-screen Receive Report -- what equipment came back to the
// pool, when, and in what condition. Consumes GET /reports/receive only
// (never GET /transactions); the backend already guarantees every row
// returned has a completed receipt (returned_at IS NOT NULL,
// unconditionally, §7.1) -- this page never filters, sorts, or otherwise
// second-guesses that.
export function ReceiveReportPage() {
  const appliedFilters = useAppliedReportFilters();
  const queryKey = ["reports", "receive", appliedFilters];

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
    queryFn: ({ pageParam }) => getReceiveReport({ ...appliedFilters, limit: 25, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
  });

  // Cursor pages are appended in exactly the order the backend returned
  // them -- never re-sorted, reversed, or merged by any client-side key.
  const rows = pages?.pages.flatMap((p) => p.items) ?? [];
  const total = pages?.pages[0]?.total;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-lg font-semibold">รายงานการรับคืน</h1>
        <p className="text-sm text-[var(--text-muted)]">
          รายการเครื่องมือที่รับคืนเข้า Pool แล้ว ตามช่วงวันที่ทำการและตัวกรองที่เลือก
        </p>
      </div>

      <ReportFilterBar />

      <div className="surface rounded-xl border p-4">
        {isLoading && <p className="text-sm text-[var(--text-muted)]">กำลังโหลดรายงานการรับคืน...</p>}
        {isError && (
          <div className="flex flex-col items-start gap-2">
            <p className="text-sm text-status-repair">{apiErrorMessage(error, "ไม่สามารถโหลดรายงานการรับคืนได้")}</p>
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
