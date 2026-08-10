import type { ImportValidationCounts } from "@/types/legacyImport";

interface LegacyImportDryRunSummaryProps {
  counts: ImportValidationCounts;
}

// PR19B "Dry-run completed / confirm-gate skeleton", shown whenever
// session.status === "dry_run_completed" -- the real backend confirm-gate
// state (design §5), not an invented separate status.
//
// No dedicated dry-run-result response shape exists in the merged PR19A
// contract: `POST /{id}/dry-run` returns only the session itself
// (`dry_run_completed_at` set); a would-create/would-skip breakdown is
// adapter-specific detail that belongs to future PR20/PR21 concrete
// adapters (design §26 Non-Goals), not this foundation. This panel
// therefore reuses the session's real validation counters instead of
// inventing execute-outcome-shaped counts with no contract to align to.
//
// The confirm action ("ยืนยันนำเข้า") is always disabled/unavailable in
// this skeleton -- task scope: "Do not execute anything." There is no code
// path anywhere in PR19B that can enable this button.
export function LegacyImportDryRunSummary({ counts }: LegacyImportDryRunSummaryProps) {
  const cards = [
    { label: "ทั้งหมด", value: counts.totalRows, accentClassName: "text-[var(--text-primary,inherit)]" },
    { label: "พร้อมนำเข้า", value: counts.validRows, accentClassName: "text-status-available" },
    { label: "มีคำเตือน", value: counts.warningRows, accentClassName: "text-status-pm" },
    { label: "ไม่ถูกต้อง", value: counts.invalidRows, accentClassName: "text-status-repair" },
  ];

  return (
    <div className="flex flex-col gap-3">
      <h3 className="text-sm font-semibold">ทดลองนำเข้าโดยไม่บันทึกแล้ว — รอการยืนยัน</h3>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {cards.map((card) => (
          <div key={card.label} className="surface flex flex-col gap-1 rounded-xl border p-3">
            <span className="text-xs text-[var(--text-muted)]">{card.label}</span>
            <span className={`text-xl font-semibold ${card.accentClassName}`}>{card.value.toLocaleString()}</span>
          </div>
        ))}
      </div>
      <div className="rounded-lg border border-[var(--border)] bg-[var(--border)]/10 p-3 text-sm">
        นี่คือการทดลองเท่านั้น ยังไม่มีการบันทึกข้อมูลลงระบบ
      </div>
      <div>
        <button
          type="button"
          disabled
          aria-disabled="true"
          aria-describedby="legacy-import-confirm-disabled-reason"
          title="การยืนยันนำเข้าจริงยังไม่พร้อมใช้งานในต้นแบบหน้าจอนี้"
          className="w-fit cursor-not-allowed rounded-lg bg-status-borrowed px-4 py-2.5 font-medium text-white opacity-50"
        >
          ยืนยันนำเข้า (ยังไม่พร้อมใช้งาน)
        </button>
        <p id="legacy-import-confirm-disabled-reason" className="mt-1 text-xs text-[var(--text-muted)]">
          ปิดใช้งานเนื่องจากต้นแบบหน้าจอนี้ยังไม่รองรับการนำเข้าข้อมูลจริง
        </p>
      </div>
    </div>
  );
}
