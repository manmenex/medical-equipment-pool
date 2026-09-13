import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { EquipmentMasterWorkflowPanel } from "@/components/EquipmentMasterWorkflowPanel";
import { LegacyHistoryWorkflowPanel } from "@/components/LegacyHistoryWorkflowPanel";
import { LegacyImportAccessGate } from "@/components/LegacyImportAccessGate";
import { canManageLegacyImport, useAuth } from "@/hooks/useAuth";
import { getImportSessionSummary } from "@/services/importSessionClient";
import { EQUIPMENT_MASTER_DATASET_TYPE } from "@/services/equipmentMasterImportClient";
import { LEGACY_TRANSACTION_HISTORY_DATASET_TYPE } from "@/services/legacyHistoryImportClient";
import { apiErrorCode } from "@/services/api";

// Roadmap PR21E: which workflow panel renders is decided by the session's
// own real `dataset_type` -- fetched once here, never inferred from the
// route/id shape (the former isBackendSessionId UUID-regex routing, which
// only ever needed to distinguish a real session from a PR19B mock
// fixture, no longer applies now that every session on this route is
// real). A session that does not exist, or whose dataset_type this
// frontend has no workflow for, both render an honest, distinct state --
// never silently falling back to the Equipment Master panel for an
// unrecognized dataset_type.
export function LegacyImportSessionDetailPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { user } = useAuth();

  const { data: session, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["legacy-import", "session-summary", sessionId],
    queryFn: () => getImportSessionSummary(sessionId as string),
    enabled: Boolean(sessionId) && canManageLegacyImport(user),
    retry: false,
  });

  const isNotFound = isError && apiErrorCode(error) === "IMPORT_SESSION_NOT_FOUND";

  return (
    <LegacyImportAccessGate>
      <div className="flex flex-col gap-4">
        <div>
          <Link to="/imports" className="text-sm text-status-borrowed hover:underline">
            ← กลับไปยังรายการนำเข้าข้อมูล
          </Link>
        </div>

        {isLoading && <p className="text-sm text-[var(--text-muted)]">กำลังโหลดรายละเอียดการนำเข้าข้อมูล...</p>}

        {isNotFound && (
          <div className="surface rounded-xl border p-4">
            <p className="text-sm font-medium text-status-repair">ไม่พบรายการนำเข้าข้อมูลนี้</p>
            <p className="mt-1 text-sm text-[var(--text-muted)]">รายการนี้อาจถูกยกเลิกหรือไม่เคยมีอยู่ในระบบ</p>
          </div>
        )}

        {isError && !isNotFound && (
          <div className="surface flex flex-col items-start gap-2 rounded-xl border p-4">
            <p className="text-sm text-status-repair">ไม่สามารถโหลดรายละเอียดการนำเข้าข้อมูลได้</p>
            <button
              type="button"
              onClick={() => refetch()}
              className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
            >
              ลองใหม่
            </button>
          </div>
        )}

        {!isLoading && !isError && session && sessionId && session.dataset_type === EQUIPMENT_MASTER_DATASET_TYPE && (
          <EquipmentMasterWorkflowPanel sessionId={sessionId} />
        )}

        {!isLoading && !isError && session && sessionId && session.dataset_type === LEGACY_TRANSACTION_HISTORY_DATASET_TYPE && (
          <LegacyHistoryWorkflowPanel sessionId={sessionId} />
        )}

        {!isLoading &&
          !isError &&
          session &&
          session.dataset_type !== EQUIPMENT_MASTER_DATASET_TYPE &&
          session.dataset_type !== LEGACY_TRANSACTION_HISTORY_DATASET_TYPE && (
            <div className="surface rounded-xl border p-4">
              <p className="text-sm font-medium text-status-repair">ไม่รองรับประเภทข้อมูลนี้</p>
              <p className="mt-1 text-sm text-[var(--text-muted)]">
                ระบบยังไม่มีหน้าจอสำหรับประเภทข้อมูล &quot;{session.dataset_type}&quot;
              </p>
            </div>
          )}
      </div>
    </LegacyImportAccessGate>
  );
}
