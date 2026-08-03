import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { LegacyImportAccessGate } from "@/components/LegacyImportAccessGate";
import { LegacyImportSkeletonBanner } from "@/components/LegacyImportSkeletonBanner";
import { LegacyImportStatusBadge } from "@/components/LegacyImportStatusBadge";
import { canManageLegacyImport, useAuth } from "@/hooks/useAuth";
import { apiErrorMessage } from "@/services/api";
import { legacyImportClient } from "@/services/legacyImportClient";
import { formatDateTimeInTimezone } from "@/utils/printFormat";
import { IMPORT_CATEGORY_LABELS } from "@/utils/legacyImportLabels";

// PR19B "Import landing/session list": docs/audits/
// 04-consolidated-implementation-plan.md Group 8 defines Roadmap PR19 as
// "a staged, validation-first, traceable import framework" -- this screen
// previews that framework's session list only. See
// types/legacyImport.ts's file-level note: nothing rendered here is a
// confirmed PR19A backend contract.
export function LegacyImportListPage() {
  const { user } = useAuth();
  // Never fires for a user the usability gate below would reject anyway --
  // mirrors the rest of this codebase's "don't call a lookup a role can't
  // use" convention (e.g. AdminPage never mounts InventoryImportPanel
  // unless canImportInventory(user) is already true).
  const { data: sessions, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["legacy-import", "sessions"],
    queryFn: () => legacyImportClient.listSessions(),
    enabled: canManageLegacyImport(user),
  });

  return (
    <LegacyImportAccessGate>
      <div className="flex flex-col gap-4">
        <LegacyImportSkeletonBanner />

        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold">นำเข้าข้อมูลเดิม</h1>
            <p className="text-sm text-[var(--text-muted)]">
              ต้นแบบขั้นตอนการนำเข้าข้อมูลเดิมจากระบบเก่า (AppSheet) สำหรับข้อมูลหลักเครื่องมือ
              ประวัติการรับคืน และประวัติการเบิก
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
              <p className="text-sm text-status-repair">{apiErrorMessage(error, "ไม่สามารถโหลดรายการนำเข้าข้อมูลได้")}</p>
              <button
                type="button"
                onClick={() => refetch()}
                className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
              >
                ลองใหม่
              </button>
            </div>
          )}
          {!isLoading && !isError && sessions && sessions.length === 0 && (
            <p className="text-sm text-[var(--text-muted)]">ยังไม่มีรายการนำเข้าข้อมูล</p>
          )}
          {!isLoading && !isError && sessions && sessions.length > 0 && (
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
                  {sessions.map((session) => (
                    <tr key={session.id} className="border-b border-[var(--border)] last:border-0">
                      <td className="py-2 pr-3">
                        <Link to={`/imports/${session.id}`} className="text-status-borrowed hover:underline">
                          {IMPORT_CATEGORY_LABELS[session.importCategory]}
                        </Link>
                      </td>
                      <td className="py-2 pr-3">{session.filename}</td>
                      <td className="py-2 pr-3">
                        <LegacyImportStatusBadge status={session.status} />
                      </td>
                      <td className="py-2 pr-3">{session.requestedByDisplayName}</td>
                      <td className="py-2 pr-3">{formatDateTimeInTimezone(session.createdAt, "Asia/Bangkok")}</td>
                      <td className="py-2 pr-3 text-[var(--text-muted)]">
                        {session.totalRows != null ? `${session.totalRows.toLocaleString()} แถว` : "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </LegacyImportAccessGate>
  );
}
