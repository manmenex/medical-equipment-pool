import { useInfiniteQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { LegacyImportAccessGate } from "@/components/LegacyImportAccessGate";
import { LegacyImportStatusBadge } from "@/components/LegacyImportStatusBadge";
import { canManageLegacyImport, useAuth } from "@/hooks/useAuth";
import { apiErrorMessage } from "@/services/api";
import { listEquipmentMasterSessions } from "@/services/equipmentMasterImportClient";
import { listLegacyHistorySessions } from "@/services/legacyHistoryImportClient";
import type { ImportCategory, ImportSessionStatus } from "@/types/legacyImport";
import { formatDateTimeInTimezone } from "@/utils/printFormat";
import { IMPORT_CATEGORY_LABELS } from "@/utils/legacyImportLabels";

interface MergedImportRow {
  id: string;
  category: ImportCategory;
  status: ImportSessionStatus;
  actorLabel: string;
  createdAt: string;
  totalRows: number | null;
}

// Roadmap PR21E (design §29-§30): this list now merges two genuinely real,
// backend-persisted sources -- Equipment Master and Legacy Transaction
// History sessions, both fetched via their own real client and both
// cursor-paginated the same way (mirrors the same pattern already used for
// equipment transaction history and DryRunPlan rows elsewhere in this
// codebase). The former PR19B mock Receive/Issue History list, and the
// "still a prototype" banner, have been removed entirely -- every session
// listed here is real.
export function LegacyImportListPage() {
  const { user } = useAuth();
  // Never fires for a user the usability gate below would reject anyway.
  const enabled = canManageLegacyImport(user);

  const {
    data: equipmentMasterPages,
    isLoading: equipmentMasterLoading,
    isError: equipmentMasterIsError,
    error: equipmentMasterError,
    refetch: refetchEquipmentMaster,
    fetchNextPage: fetchNextEquipmentMasterPage,
    hasNextPage: hasNextEquipmentMasterPage,
    isFetchingNextPage: isFetchingNextEquipmentMasterPage,
  } = useInfiniteQuery({
    queryKey: ["legacy-import", "equipment-master", "sessions"],
    queryFn: ({ pageParam }) => listEquipmentMasterSessions({ limit: 50, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    enabled,
  });
  const equipmentMasterItems = equipmentMasterPages?.pages.flatMap((p) => p.items) ?? [];
  const equipmentMasterTotal = equipmentMasterPages?.pages[0]?.total ?? null;

  const {
    data: legacyHistoryPages,
    isLoading: legacyHistoryLoading,
    isError: legacyHistoryIsError,
    error: legacyHistoryError,
    refetch: refetchLegacyHistory,
    fetchNextPage: fetchNextLegacyHistoryPage,
    hasNextPage: hasNextLegacyHistoryPage,
    isFetchingNextPage: isFetchingNextLegacyHistoryPage,
  } = useInfiniteQuery({
    queryKey: ["legacy-import", "legacy-history", "sessions"],
    queryFn: ({ pageParam }) => listLegacyHistorySessions({ limit: 50, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    enabled,
  });
  const legacyHistoryItems = legacyHistoryPages?.pages.flatMap((p) => p.items) ?? [];
  const legacyHistoryTotal = legacyHistoryPages?.pages[0]?.total ?? null;

  const isLoading = equipmentMasterLoading || legacyHistoryLoading;
  const isError = equipmentMasterIsError || legacyHistoryIsError;

  function refetchBoth() {
    refetchEquipmentMaster();
    refetchLegacyHistory();
  }

  // Neither real ImportSessionOut carries a filename (that belongs to the
  // separate ImportSource resource, registered via source/upload) or a
  // display name (only created_by_user_id, a user id reference with no
  // name-resolution endpoint in this contract) -- both rendered honestly
  // as the raw id rather than fetched per-row or fabricated.
  const equipmentMasterRows: MergedImportRow[] = equipmentMasterItems.map((session) => ({
    id: session.id,
    category: "equipment_master",
    status: session.status,
    actorLabel: session.created_by_user_id,
    createdAt: session.created_at,
    totalRows: session.total_rows,
  }));
  const legacyHistoryRows: MergedImportRow[] = legacyHistoryItems.map((session) => ({
    id: session.id,
    category: "legacy_transaction_history",
    status: session.status,
    actorLabel: session.created_by_user_id,
    createdAt: session.created_at,
    totalRows: session.total_rows,
  }));

  const rows = [...equipmentMasterRows, ...legacyHistoryRows].sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1));
  const hasNextPage = hasNextEquipmentMasterPage || hasNextLegacyHistoryPage;

  return (
    <LegacyImportAccessGate>
      <div className="flex flex-col gap-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold">นำเข้าข้อมูลเดิม</h1>
            <p className="text-sm text-[var(--text-muted)]">
              นำเข้าข้อมูลเดิมจากระบบเก่า (AppSheet) สำหรับข้อมูลหลักเครื่องมือ และประวัติการรับ-ส่งเครื่องมือเดิม
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
                {apiErrorMessage(equipmentMasterError ?? legacyHistoryError, "ไม่สามารถโหลดรายการนำเข้าข้อมูลได้")}
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
                          {IMPORT_CATEGORY_LABELS[row.category]}
                        </Link>
                      </td>
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
          {!isLoading && !isError && hasNextPage && (
            <button
              type="button"
              onClick={() => {
                if (hasNextEquipmentMasterPage) fetchNextEquipmentMasterPage();
                if (hasNextLegacyHistoryPage) fetchNextLegacyHistoryPage();
              }}
              disabled={isFetchingNextEquipmentMasterPage || isFetchingNextLegacyHistoryPage}
              className="mt-3 rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium disabled:opacity-50"
            >
              {isFetchingNextEquipmentMasterPage || isFetchingNextLegacyHistoryPage ? "กำลังโหลด..." : "โหลดเพิ่มเติม"}
            </button>
          )}
          {!isLoading && !isError && !hasNextPage && (equipmentMasterTotal !== null || legacyHistoryTotal !== null) && rows.length > 0 && (
            <p className="mt-2 text-xs text-[var(--text-muted)]">
              ข้อมูลหลักเครื่องมือ: แสดง {equipmentMasterItems.length.toLocaleString()} จาก {(equipmentMasterTotal ?? 0).toLocaleString()} รายการ ·
              ประวัติการรับ-ส่งเครื่องมือเดิม: แสดง {legacyHistoryItems.length.toLocaleString()} จาก {(legacyHistoryTotal ?? 0).toLocaleString()} รายการ
            </p>
          )}
        </div>
      </div>
    </LegacyImportAccessGate>
  );
}
