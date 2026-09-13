import { useInfiniteQuery } from "@tanstack/react-query";
import { useLocation } from "react-router-dom";

import { EquipmentVerifyChecklistFilterBar } from "@/components/EquipmentVerifyChecklistFilterBar";
import { EquipmentVerifyChecklistTable } from "@/components/EquipmentVerifyChecklistTable";
import { useAppliedVerifyChecklistFilters } from "@/hooks/useAppliedVerifyChecklistFilters";
import { apiErrorMessage } from "@/services/api";
import { getEquipmentVerifyChecklist } from "@/services/reports";

// Roadmap PR17 Slice 4 (docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md
// §6.3/§7.3(A)/§8/§10.3/§12, Owner Decision #1 resolved to interpretation
// A): the final functional slice of PR17 -- a read-only, current-state
// listing of the pool's own equipment master records and their status.
// Consumes GET /reports/equipment-verify-checklist only. Not a
// transaction/event report: no business date/shift filter (§7.3(A) --
// this report has no date/shift basis at all), and rows are rendered
// exactly as returned, with no eligibility/lifecycle logic computed here.
export function EquipmentVerifyChecklistPage() {
  const appliedFilters = useAppliedVerifyChecklistFilters();
  const queryKey = ["reports", "equipment-verify-checklist", appliedFilters];
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
    queryFn: ({ pageParam }) => getEquipmentVerifyChecklist({ ...appliedFilters, limit: 25, cursor: pageParam }),
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
          <h1 className="text-lg font-semibold">รายการตรวจสอบเครื่องมือ</h1>
          <p className="text-sm text-[var(--text-muted)]">
            รายการเครื่องมือและสถานะปัจจุบันในระบบ ตามตัวกรองที่เลือก
          </p>
        </div>
        {/* Roadmap PR18C: opens the dedicated print view in a new tab,
            carrying this page's currently applied URL filters over
            verbatim -- the print view never re-derives them. */}
        <a
          href={`/reports/equipment-verify-checklist/print${location.search}`}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
        >
          พิมพ์รายงาน
        </a>
      </div>

      <EquipmentVerifyChecklistFilterBar />

      <div className="surface rounded-xl border p-4">
        {isLoading && <p className="text-sm text-[var(--text-muted)]">กำลังโหลดรายการตรวจสอบเครื่องมือ...</p>}
        {isError && (
          <div className="flex flex-col items-start gap-2">
            <p className="text-sm text-status-repair">
              {apiErrorMessage(error, "ไม่สามารถโหลดรายการตรวจสอบเครื่องมือได้")}
            </p>
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
            <EquipmentVerifyChecklistTable rows={rows} />
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
