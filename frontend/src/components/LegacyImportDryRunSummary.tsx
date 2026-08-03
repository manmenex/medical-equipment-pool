import type { ImportDryRunSummary } from "@/types/legacyImport";

interface LegacyImportDryRunSummaryProps {
  summary: ImportDryRunSummary;
}

// PR19B "Dry-run summary skeleton". The confirm action ("ยืนยันนำเข้า") is
// always disabled/unavailable in this skeleton -- task scope: "Do not
// execute anything." There is no code path anywhere in PR19B that can
// enable this button.
export function LegacyImportDryRunSummary({ summary }: LegacyImportDryRunSummaryProps) {
  const cards = [
    { label: "จะสร้างรายการใหม่", value: summary.wouldCreateCount, accentClassName: "text-status-available" },
    { label: "จะข้าม", value: summary.wouldSkipCount, accentClassName: "text-status-out_of_service" },
    { label: "รายการซ้ำ", value: summary.duplicateCount, accentClassName: "text-status-calibration" },
    { label: "ตรวจสอบไม่ผ่าน", value: summary.validationFailureCount, accentClassName: "text-status-repair" },
    { label: "คำเตือน", value: summary.warningCount, accentClassName: "text-status-pm" },
  ];

  return (
    <div className="flex flex-col gap-3">
      <h3 className="text-sm font-semibold">สรุปผลทดลองนำเข้าโดยไม่บันทึก</h3>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-5">
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
