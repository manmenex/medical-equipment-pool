import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { LegacyImportAccessGate } from "@/components/LegacyImportAccessGate";
import { LegacyImportStatusBadge } from "@/components/LegacyImportStatusBadge";
import { canManageLegacyImport, useAuth } from "@/hooks/useAuth";
import { apiErrorMessage } from "@/services/api";
import { legacyImportClient } from "@/services/legacyImportClient";
import { listEquipmentMasterSessions } from "@/services/equipmentMasterImportClient";
import type { ImportSessionStatus } from "@/types/legacyImport";
import { formatDateTimeInTimezone } from "@/utils/printFormat";
import { IMPORT_CATEGORY_LABELS } from "@/utils/legacyImportLabels";

interface MergedImportRow {
  id: string;
  categoryLabel: string;
  filename: string;
  status: ImportSessionStatus;
  actorLabel: string;
  createdAt: string;
  totalRows: number | null;
}

// PR19B "Import landing/session list" + PR20F "Equipment Master real API
// integration" (design §35): this list merges two genuinely different
// sources -- real, backend-persisted Equipment Master sessions (fetched via
// services/equipmentMasterImportClient.ts) and the still-mock Receive/Issue
// History sessions (services/legacyImportClient.ts's MockImportClient,
// explicitly filtered to exclude equipment_master so a category is never
// listed from both sources at once). Receive/Issue History remain
// frontend-only placeholders -- see legacyImportFixtures.ts's file-level
// note -- and are never routed through the real Equipment Master client.
export function LegacyImportListPage() {
  const { user } = useAuth();
  // Never fires for a user the usability gate below would reject anyway --
  // mirrors the rest of this codebase's "don't call a lookup a role can't
  // use" convention (e.g. AdminPage never mounts InventoryImportPanel
  // unless canImportInventory(user) is already true).
  // Review round 1 (P1 "Legacy Import session list must paginate"): a
  // single limit:50 fetch silently hid every real Equipment Master session
  // beyond the first page. useInfiniteQuery follows the backend's own
  // next_cursor through an explicit "โหลดเพิ่มเติม" action instead of
  // discarding it -- mirroring the same cursor pattern already used for
  // equipment transaction history (EquipmentDetailPage) and DryRunPlan rows
  // (EquipmentMasterWorkflowPanel). The mock Receive/Issue list has no
  // pagination concern of its own -- MockImportClient.listSessions() always
  // returns its full, small fixture set in one page (nextCursor: null).
  const {
    data: realPages,
    isLoading: realLoading,
    isError: realIsError,
    error: realError,
    refetch: refetchReal,
    fetchNextPage: fetchNextRealPage,
    hasNextPage: hasNextRealPage,
    isFetchingNextPage: isFetchingNextRealPage,
  } = useInfiniteQuery({
    queryKey: ["legacy-import", "equipment-master", "sessions"],
    queryFn: ({ pageParam }) => listEquipmentMasterSessions({ limit: 50, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    enabled: canManageLegacyImport(user),
  });
  const realItems = realPages?.pages.flatMap((p) => p.items) ?? [];
  const realTotal = realPages?.pages[0]?.total ?? null;
  const {
    data: mockPage,
    isLoading: mockLoading,
    isError: mockIsError,
    error: mockError,
    refetch: refetchMock,
  } = useQuery({
    queryKey: ["legacy-import", "sessions"],
    queryFn: () => legacyImportClient.listSessions(),
    enabled: canManageLegacyImport(user),
  });

  const isLoading = realLoading || mockLoading;
  const isError = realIsError || mockIsError;

  function refetchBoth() {
    refetchReal();
    refetchMock();
  }

  const mockRows: MergedImportRow[] = (mockPage?.items ?? [])
    .filter((session) => session.datasetType !== "equipment_master")
    .map((session) => ({
      id: session.id,
      categoryLabel: IMPORT_CATEGORY_LABELS[session.datasetType],
      filename: session.filename,
      status: session.status,
      actorLabel: session.requestedByDisplayName,
      createdAt: session.createdAt,
      totalRows: session.totalRows,
    }));

  // The real ImportSessionOut carries no filename (that belongs to the
  // separate ImportSource resource, registered via source/upload) and no
  // display name (only created_by_user_id, a user id reference with no
  // name-resolution endpoint in this contract) -- both rendered honestly
  // as "-"/the raw id rather than fetched per-row or fabricated.
  const realRows: MergedImportRow[] = realItems.map((session) => ({
    id: session.id,
    categoryLabel: IMPORT_CATEGORY_LABELS.equipment_master,
    filename: "-",
    status: session.status,
    actorLabel: session.created_by_user_id,
    createdAt: session.created_at,
    totalRows: session.total_rows,
  }));

  const rows = [...realRows, ...mockRows].sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1));

  return (
    <LegacyImportAccessGate>
      <div className="flex flex-col gap-4">
        <div className="rounded-lg border border-dashed border-status-pm bg-status-pm/10 px-3 py-2 text-sm font-medium text-status-pm">
          ข้อมูลหลักเครื่องมือเชื่อมต่อระบบจริงแล้ว — ประวัติการรับคืนและประวัติการเบิกยังเป็นต้นแบบ ยังไม่มีการนำเข้าข้อมูลจริง
        </div>

        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold">นำเข้าข้อมูลเดิม</h1>
            <p className="text-sm text-[var(--text-muted)]">
              นำเข้าข้อมูลเดิมจากระบบเก่า (AppSheet) สำหรับข้อมูลหลักเครื่องมือ ประวัติการรับคืน และประวัติการเบิก
            </p>
          </div>
          <Link
            to="/imports/new"
            className="shrink-0 rounded-lg bg-status-borrowed px-4 py-2.5 text-sm font-medium text-white"
          >
            เริ่มนำเข้าข้อมูล
          </Link>
        </div>

        <div className="surface rounded-xl border p-4">
          {isLoading && <p className="text-sm text-[var(--text-muted)]">กำลังโหลดรายการนำเข้าข้อมูล...</p>}
          {isError && (
            <div className="flex flex-col items-start gap-2">
              <p className="text-sm text-status-repair">
                {apiErrorMessage(realError ?? mockError, "ไม่สามารถโหลดรายการนำเข้าข้อมูลได้")}
              </p>
              <button
                type="button"
                onClick={refetchBoth}
                className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
              >
                ลองใหม่
              </button>
            </div>
          )}
          {!isLoading && !isError && rows.length === 0 && (
            <p className="text-sm text-[var(--text-muted)]">ยังไม่มีรายการนำเข้าข้อมูล</p>
          )}
          {!isLoading && !isError && rows.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-left text-sm">
                <thead>
                  <tr className="border-b border-[var(--border)] text-xs text-[var(--text-muted)]">
                    <th scope="col" className="py-2 pr-3 font-medium">
                      ประเภทข้อมูล
                    </th>
                    <th scope="col" className="py-2 pr-3 font-medium">
                      ไฟล์
                    </th>
                    <th scope="col" className="py-2 pr-3 font-medium">
                      สถานะ
                    </th>
                    <th scope="col" className="py-2 pr-3 font-medium">
                      ผู้ดำเนินการ
                    </th>
                    <th scope="col" className="py-2 pr-3 font-medium">
                      วันที่สร้าง
                    </th>
                    <th scope="col" className="py-2 pr-3 font-medium">
                      สรุปจำนวน
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id} className="border-b border-[var(--border)] last:border-0">
                      <td className="py-2 pr-3">
                        <Link to={`/imports/${row.id}`} className="text-status-borrowed hover:underline">
                          {row.categoryLabel}
                        </Link>
                      </td>
                      <td className="py-2 pr-3">{row.filename}</td>
                      <td className="py-2 pr-3">
                        <LegacyImportStatusBadge status={row.status} />
                      </td>
                      <td className="py-2 pr-3">{row.actorLabel}</td>
                      <td className="py-2 pr-3">{formatDateTimeInTimezone(row.createdAt, "Asia/Bangkok")}</td>
                      <td className="py-2 pr-3 text-[var(--text-muted)]">
                        {row.totalRows != null ? `${row.totalRows.toLocaleString()} แถว` : "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {!isLoading && !isError && hasNextRealPage && (
            <button
              type="button"
              onClick={() => fetchNextRealPage()}
              disabled={isFetchingNextRealPage}
              className="mt-3 rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium disabled:opacity-50"
            >
              {isFetchingNextRealPage ? "กำลังโหลด..." : "โหลดเพิ่มเติม"}
            </button>
          )}
          {!isLoading && !isError && !hasNextRealPage && realTotal !== null && realItems.length > 0 && (
            <p className="mt-2 text-xs text-[var(--text-muted)]">
              ข้อมูลหลักเครื่องมือ: แสดง {realItems.length.toLocaleString()} จาก {realTotal.toLocaleString()} รายการ
            </p>
          )}
        </div>
      </div>
    </LegacyImportAccessGate>
  );
}
