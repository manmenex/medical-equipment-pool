import { formatDateTimeInTimezone } from "@/utils/printFormat";
import type { ImportResultSummary } from "@/types/legacyImport";
import { LegacyImportStatusBadge } from "@/components/LegacyImportStatusBadge";

// PR19B "Result summary skeleton". No PR19B code path can ever produce this
// from a live action -- it only ever renders a pre-existing example
// fixture session, never as the outcome of pressing a button in this
// skeleton (task scope: "No real result generation").
export function LegacyImportResultSummary({ result }: { result: ImportResultSummary }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold">สรุปผลการนำเข้า</h3>
        <LegacyImportStatusBadge status={result.status} />
      </div>
      <div className="grid grid-cols-3 gap-3">
        <div className="surface flex flex-col gap-1 rounded-xl border p-3">
          <span className="text-xs text-[var(--text-muted)]">นำเข้าสำเร็จ</span>
          <span className="text-xl font-semibold text-status-available">{result.importedCount.toLocaleString()}</span>
        </div>
        <div className="surface flex flex-col gap-1 rounded-xl border p-3">
          <span className="text-xs text-[var(--text-muted)]">ข้าม</span>
          <span className="text-xl font-semibold text-status-out_of_service">{result.skippedCount.toLocaleString()}</span>
        </div>
        <div className="surface flex flex-col gap-1 rounded-xl border p-3">
          <span className="text-xs text-[var(--text-muted)]">ล้มเหลว</span>
          <span className="text-xl font-semibold text-status-repair">{result.failedCount.toLocaleString()}</span>
        </div>
      </div>
      <dl className="grid grid-cols-1 gap-1 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs text-[var(--text-muted)]">เลขอ้างอิงรายการนำเข้า</dt>
          <dd>{result.sessionReference}</dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--text-muted)]">เวลาสิ้นสุด</dt>
          <dd>{result.completedAt ? formatDateTimeInTimezone(result.completedAt, "Asia/Bangkok") : "-"}</dd>
        </div>
      </dl>
    </div>
  );
}
