import { formatDateTimeInTimezone } from "@/utils/printFormat";
import type { ImportResultSummary } from "@/types/legacyImport";
import { LegacyImportStatusBadge } from "@/components/LegacyImportStatusBadge";

// PR19B "Result summary skeleton". No PR19B code path can ever produce this
// from a live action -- it only ever renders a pre-existing example
// fixture session, never as the outcome of pressing a button in this
// skeleton (task scope: "No real result generation"). Mirrors what
// actually exists on the real `ImportSessionOut` once execute completes:
// `status`, `imported_rows`, `terminal_at`, and the session's own `id` --
// no `skippedCount`/`failedCount` field exists in that contract.
//
// Presentation is status-specific, never a single hardcoded "success"
// card: a FAILED execution rolls back every domain write it attempted
// (design §19) and a CANCELLED session never reaches execute at all
// (design §5) -- neither has rows to claim as imported, so both render a
// non-success message instead of the green completed card.
//
// `importedRows` (nullable, see types/legacyImport.ts) is never coerced
// to 0 -- null and 0 are different facts (0 = backend explicitly reports
// zero imported rows; null = no count available for this outcome) and
// collapsing them would let the UI assert "นำเข้า 0 แถว" for an outcome
// that never actually reported a count. A completed session in this
// skeleton's own fixtures always has a real, non-null count (enforced by
// assertImportSessionInvariants), but the component itself stays honest
// about the nullable type rather than silently fabricating a number for
// any input it's given.
export function LegacyImportResultSummary({ result }: { result: ImportResultSummary }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold">สรุปผลการนำเข้า</h3>
        <LegacyImportStatusBadge status={result.status} />
      </div>

      {result.status === "completed" && (
        <div className="surface flex w-fit flex-col gap-1 rounded-xl border p-3">
          <span className="text-xs text-[var(--text-muted)]">จำนวนแถวที่นำเข้าสำเร็จ</span>
          {result.importedRows !== null ? (
            <span className="text-xl font-semibold text-status-available">
              {result.importedRows.toLocaleString()}
            </span>
          ) : (
            <span className="text-sm text-[var(--text-muted)]">ไม่ทราบจำนวนแถวที่นำเข้า</span>
          )}
        </div>
      )}

      {result.status === "failed" && (
        <div className="surface flex w-fit flex-col gap-1 rounded-xl border border-status-repair/40 bg-status-repair/5 p-3">
          <span className="text-sm font-medium text-status-repair">การนำเข้าล้มเหลว</span>
          <span className="text-xs text-[var(--text-muted)]">
            ไม่มีข้อมูลถูกบันทึกลงระบบ -- การเปลี่ยนแปลงทั้งหมดของความพยายามนี้ถูกยกเลิก
          </span>
        </div>
      )}

      {result.status === "cancelled" && (
        <div className="surface flex w-fit flex-col gap-1 rounded-xl border p-3">
          <span className="text-sm font-medium">ยกเลิกการนำเข้า</span>
          <span className="text-xs text-[var(--text-muted)]">
            ยกเลิกก่อนเริ่มขั้นตอนบันทึกข้อมูล -- ไม่มีข้อมูลถูกนำเข้า
          </span>
        </div>
      )}

      <dl className="grid grid-cols-1 gap-1 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs text-[var(--text-muted)]">เลขอ้างอิงรายการนำเข้า</dt>
          <dd>{result.sessionId}</dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--text-muted)]">เวลาสิ้นสุด</dt>
          <dd>{result.terminalAt ? formatDateTimeInTimezone(result.terminalAt, "Asia/Bangkok") : "-"}</dd>
        </div>
      </dl>
    </div>
  );
}
