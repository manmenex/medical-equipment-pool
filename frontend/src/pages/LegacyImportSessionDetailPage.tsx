import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { LegacyImportAccessGate } from "@/components/LegacyImportAccessGate";
import { LegacyImportDryRunSummary } from "@/components/LegacyImportDryRunSummary";
import { LegacyImportIssuesTable } from "@/components/LegacyImportIssuesTable";
import { LegacyImportResultSummary } from "@/components/LegacyImportResultSummary";
import { LegacyImportSkeletonBanner } from "@/components/LegacyImportSkeletonBanner";
import { LegacyImportStatusBadge } from "@/components/LegacyImportStatusBadge";
import { LegacyImportValidationSummary } from "@/components/LegacyImportValidationSummary";
import { EquipmentMasterWorkflowPanel } from "@/components/EquipmentMasterWorkflowPanel";
import { canManageLegacyImport, useAuth } from "@/hooks/useAuth";
import { ImportSessionNotFoundError, legacyImportClient } from "@/services/legacyImportClient";
import { formatDateTimeInTimezone } from "@/utils/printFormat";
import { IMPORT_CATEGORY_LABELS, formatFileSize } from "@/utils/legacyImportLabels";
import { isBackendSessionId } from "@/utils/legacyImportSessionId";

// PR19B "Import session details" (mock path) + PR20F "Equipment Master
// real workflow" (real path). Which path renders is decided purely by
// `isBackendSessionId(sessionId)` (utils/legacyImportSessionId.ts) --
// routing only, never a business decision. The mock path below is
// unchanged from PR19B and continues to serve Receive/Issue History,
// which remain frontend-only placeholders (design §34).
export function LegacyImportSessionDetailPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { user } = useAuth();
  const isRealSession = isBackendSessionId(sessionId);

  const { data: session, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["legacy-import", "session", sessionId],
    queryFn: () => legacyImportClient.getSession(sessionId as string),
    enabled: Boolean(sessionId) && canManageLegacyImport(user) && !isRealSession,
    retry: false,
  });

  const isNotFound = isError && error instanceof ImportSessionNotFoundError;
  // The confirm-gate panel appears exactly when the session is sitting in
  // the real backend's own confirm-gate status (design §5) -- not an
  // invented "awaiting confirmation" status.
  const isAwaitingConfirmation = session?.status === "dry_run_completed";

  if (isRealSession) {
    return (
      <LegacyImportAccessGate>
        <div className="flex flex-col gap-4">
          <div>
            <Link to="/imports" className="text-sm text-status-borrowed hover:underline">
              ← กลับไปยังรายการนำเข้าข้อมูล
            </Link>
          </div>
          <EquipmentMasterWorkflowPanel sessionId={sessionId as string} />
        </div>
      </LegacyImportAccessGate>
    );
  }

  return (
    <LegacyImportAccessGate>
      <div className="flex flex-col gap-4">
        <LegacyImportSkeletonBanner />

        <div>
          <Link to="/imports" className="text-sm text-status-borrowed hover:underline">
            ← กลับไปยังรายการนำเข้าข้อมูล
          </Link>
        </div>

        {isLoading && <p className="text-sm text-[var(--text-muted)]">กำลังโหลดรายละเอียดการนำเข้าข้อมูล...</p>}

        {isNotFound && (
          <div className="surface rounded-xl border p-4">
            <p className="text-sm font-medium text-status-repair">ไม่พบรายการนำเข้าข้อมูลนี้</p>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              รายการนี้อาจถูกยกเลิกหรือไม่เคยมีอยู่ในระบบ
            </p>
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

        {!isLoading && !isError && session && (
          <div className="flex flex-col gap-4">
            <div className="surface rounded-xl border p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h1 className="text-lg font-semibold">{IMPORT_CATEGORY_LABELS[session.datasetType]}</h1>
                  <p className="text-sm text-[var(--text-muted)]">
                    {session.filename} · {formatFileSize(session.requestedFileSizeBytes)}
                  </p>
                </div>
                <LegacyImportStatusBadge status={session.status} />
              </div>
              <dl className="mt-3 grid grid-cols-1 gap-2 text-sm sm:grid-cols-3">
                <div>
                  <dt className="text-xs text-[var(--text-muted)]">เลขอ้างอิงรายการ</dt>
                  <dd>{session.id}</dd>
                </div>
                <div>
                  <dt className="text-xs text-[var(--text-muted)]">ผู้ดำเนินการ</dt>
                  <dd>{session.requestedByDisplayName}</dd>
                </div>
                <div>
                  <dt className="text-xs text-[var(--text-muted)]">วันที่สร้าง</dt>
                  <dd>{formatDateTimeInTimezone(session.createdAt, "Asia/Bangkok")}</dd>
                </div>
              </dl>
            </div>

            {session.validationCounts && (
              <div className="surface rounded-xl border p-4">
                <LegacyImportValidationSummary
                  counts={session.validationCounts}
                  findingsByCategory={session.findingsByCategory}
                />
              </div>
            )}

            {session.findings.length > 0 && (
              <div className="surface rounded-xl border p-4">
                <h3 className="mb-3 text-sm font-semibold">รายการที่ต้องตรวจสอบ</h3>
                <LegacyImportIssuesTable findings={session.findings} />
              </div>
            )}

            {isAwaitingConfirmation && session.validationCounts && (
              <div className="surface rounded-xl border p-4">
                <LegacyImportDryRunSummary counts={session.validationCounts} />
              </div>
            )}

            {session.resultSummary && (
              <div className="surface rounded-xl border p-4">
                <LegacyImportResultSummary result={session.resultSummary} />
              </div>
            )}
          </div>
        )}
      </div>
    </LegacyImportAccessGate>
  );
}
