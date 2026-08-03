import type { ImportValidationSummary } from "@/types/legacyImport";

// PR19B "Validation summary skeleton": mock/sample counts only -- never
// calculated from a real selected file (task scope boundary).
export function LegacyImportValidationSummary({ summary }: { summary: ImportValidationSummary }) {
  const cards: { label: string; value: number; accentClassName: string }[] = [
    { label: "ทั้งหมด", value: summary.totalRows, accentClassName: "text-[var(--text-primary,inherit)]" },
    { label: "รายการที่ถูกต้อง", value: summary.validRows, accentClassName: "text-status-available" },
    { label: "รายการที่มีคำเตือน", value: summary.warningRows, accentClassName: "text-status-pm" },
    { label: "รายการที่ไม่ถูกต้อง", value: summary.invalidRows, accentClassName: "text-status-repair" },
    { label: "รายการซ้ำ", value: summary.duplicateRows, accentClassName: "text-status-calibration" },
  ];

  return (
    <div className="flex flex-col gap-3">
      <h3 className="text-sm font-semibold">สรุปผลการตรวจสอบข้อมูล</h3>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-5">
        {cards.map((card) => (
          <div key={card.label} className="surface flex flex-col gap-1 rounded-xl border p-3">
            <span className="text-xs text-[var(--text-muted)]">{card.label}</span>
            <span className={`text-xl font-semibold ${card.accentClassName}`}>{card.value.toLocaleString()}</span>
          </div>
        ))}
      </div>
      {summary.byCategory.length > 0 && (
        <div className="surface rounded-xl border p-3">
          <p className="mb-2 text-xs font-medium text-[var(--text-muted)]">สรุปตามประเภทปัญหา</p>
          <ul className="flex flex-col gap-1 text-sm">
            {summary.byCategory.map((item) => (
              <li key={item.categoryLabelTh} className="flex items-center justify-between gap-2">
                <span>{item.categoryLabelTh}</span>
                <span className="font-medium">{item.count.toLocaleString()}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
