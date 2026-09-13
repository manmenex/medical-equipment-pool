import { PRINT_ORIENTATION, formatDateTimeInTimezone, formatPrintValue } from "@/utils/printFormat";
import type { PrintDocumentOut } from "@/types";

// Roadmap PR18C (docs/design/PR18_PRINTING_EXPORT_PLAN.md §9/§16): the
// print presentation for one PrintDocumentOut. Purely presentational --
// renders exactly the metadata, applied-filter summary, column order, and
// row order the backend returned, in the order given. It must never
// filter, sort, resolve a UUID, or recompute a value; every value shown
// here already came from the backend-authoritative document.
//
// Branding fallback (design §16, Owner Decision #2 unresolved but design
// gives an explicit interim fallback): no hospital name, no logo -- a
// product-neutral Thai title plus "Medical Equipment Pool" as a secondary
// system label, and a neutral footer with report identity, template
// version, and generation time. No hospital identity is assumed or
// hardcoded.
export function PrintDocumentView({ document }: { document: PrintDocumentOut }) {
  const { metadata, columns, rows } = document;
  const orientation = PRINT_ORIENTATION[metadata.report_identity];
  const isEmpty = rows.length === 0;

  return (
    <div className="print-root" data-orientation={orientation}>
      <div className="print-page">
        <div className="print-sheet">
          <header className="print-header mb-4">
            <p className="text-xs text-[#64748b]">Medical Equipment Pool</p>
            <h1 className="text-xl font-bold">{metadata.display_name_th}</h1>
          </header>

          <section className="mb-4 grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-[#334155] sm:grid-cols-4">
            <div>
              <span className="text-[#64748b]">สร้างเมื่อ: </span>
              {formatDateTimeInTimezone(metadata.generated_at, metadata.timezone)} ({metadata.timezone})
            </div>
            <div>
              <span className="text-[#64748b]">สร้างโดย: </span>
              {metadata.generated_by_display_name}
            </div>
            <div>
              <span className="text-[#64748b]">รหัสรายงาน: </span>
              {metadata.report_identity}
            </div>
            <div>
              <span className="text-[#64748b]">เวอร์ชันเอกสาร: </span>
              {metadata.template_version}
            </div>
          </section>

          {metadata.applied_filters.length > 0 && (
            <section className="mb-4 rounded-lg border border-[#e2e8f0] p-3 text-xs">
              <h2 className="mb-1 font-medium">ตัวกรองที่ใช้</h2>
              <ul className="grid grid-cols-2 gap-x-6 gap-y-0.5 sm:grid-cols-3">
                {metadata.applied_filters.map((f) => (
                  <li key={f.label_th}>
                    <span className="text-[#64748b]">{f.label_th}: </span>
                    {f.value}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <p className="mb-2 text-xs text-[#64748b]">พบทั้งหมด {metadata.row_count} รายการ</p>

          {isEmpty ? (
            <p className="rounded-lg border border-dashed border-[#cbd5e1] p-6 text-center text-sm text-[#64748b]">
              ไม่พบข้อมูลตามตัวกรองที่เลือก
            </p>
          ) : (
            <table className="print-table">
              <thead>
                <tr>
                  {columns.map((c) => (
                    <th key={c.key}>{c.label_th}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  // Backend order preserved exactly -- index is a stable
                  // key only because rows are never reordered or filtered
                  // client-side after this array is received.
                  <tr key={index}>
                    {columns.map((c) => (
                      <td key={c.key}>{formatPrintValue(row.values[c.key], c.value_type)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <footer className="mt-4 border-t border-[#e2e8f0] pt-2 text-[10px] text-[#94a3b8]">
            {metadata.report_identity} · เวอร์ชันเอกสาร {metadata.template_version} · สร้างเมื่อ{" "}
            {formatDateTimeInTimezone(metadata.generated_at, metadata.timezone)} ({metadata.timezone})
          </footer>
        </div>
      </div>
    </div>
  );
}
