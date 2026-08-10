import type { ImportFindingCategoryCount, ImportValidationCounts } from "@/types/legacyImport";

interface LegacyImportValidationSummaryProps {
  counts: ImportValidationCounts;
  findingsByCategory: ImportFindingCategoryCount[];
}

// PR19B "Validation summary skeleton": mock/sample counts only -- never
// calculated from a real selected file (task scope boundary). `counts`
// mirrors the real ImportSessionOut fields (total_rows/valid_rows/
// warning_rows/invalid_rows) -- no `duplicateRows` field exists in the
// merged backend contract; a duplicate is one specific finding error code
// instead (see the issues table below).
export function LegacyImportValidationSummary({ counts, findingsByCategory }: LegacyImportValidationSummaryProps) {
  const cards: { label: string; value: number; accentClassName: string }[] = [
    { label: "ทั้งหมด", value: counts.totalRows, accentClassName: "text-[var(--text-primary,inherit)]" },
    { label: "รายการที่ถูกต้อง", value: counts.validRows, accentClassName: "text-status-available" },
    { label: "รายการที่มีคำเตือน", value: counts.warningRows, accentClassName: "text-status-pm" },
    { label: "รายการที่ไม่ถูกต้อง", value: counts.invalidRows, accentClassName: "text-status-repair" },
  ];

  return (
    <div className="flex flex-col gap-3">
      <h3 className="text-sm font-semibold">สรุปผลการตรวจสอบข้อมูล</h3>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {cards.map((card) => (
          <div key={card.label} className="surface flex flex-col gap-1 rounded-xl border p-3">
            <span className="text-xs text-[var(--text-muted)]">{card.label}</span>
            <span className={`text-xl font-semibold ${card.accentClassName}`}>{card.value.toLocaleString()}</span>
          </div>
        ))}
      </div>
      {counts.warningRows > 0 && (
        <p className="text-xs text-[var(--text-muted)]">
          คำเตือนไม่ปิดกั้นการดำเนินการต่อ — สามารถทดลองนำเข้าโดยไม่บันทึกต่อได้แม้มีคำเตือน
        </p>
      )}
      {findingsByCategory.length > 0 && (
        <div className="surface rounded-xl border p-3">
          <p className="mb-2 text-xs font-medium text-[var(--text-muted)]">สรุปตามประเภทปัญหา</p>
          <ul className="flex flex-col gap-1 text-sm">
            {findingsByCategory.map((item) => (
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
