import type { ImportFinding } from "@/types/legacyImport";
import { IMPORT_FINDING_SEVERITY_COLORS, IMPORT_FINDING_SEVERITY_LABELS } from "@/utils/legacyImportLabels";

function SeverityBadge({ severity }: { severity: ImportFinding["severity"] }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${IMPORT_FINDING_SEVERITY_COLORS[severity]}`}
    >
      {IMPORT_FINDING_SEVERITY_LABELS[severity]}
    </span>
  );
}

// PR19B "Row-level findings skeleton": representative mock rows only,
// shaped like the real backend's ValidationFindingOut
// (id/row_number/field/error_code/message/severity) -- no `submittedValue`
// field exists in that contract, so the offending value (if relevant) is
// folded into `message` text instead. Renders a table on wider screens and
// a stacked-card fallback on small screens (task brief, Accessibility:
// "responsive tables or card fallback on small screens").
export function LegacyImportIssuesTable({ findings }: { findings: ImportFinding[] }) {
  if (findings.length === 0) {
    return <p className="text-sm text-[var(--text-muted)]">ไม่พบรายการที่มีปัญหา</p>;
  }

  return (
    <div>
      <div className="hidden overflow-x-auto sm:block">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead>
            <tr className="border-b border-[var(--border)] text-xs text-[var(--text-muted)]">
              <th scope="col" className="py-2 pr-3 font-medium">
                แถว
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                ฟิลด์
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                รหัสปัญหา
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                คำอธิบาย
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                ระดับ
              </th>
            </tr>
          </thead>
          <tbody>
            {findings.map((finding) => (
              <tr key={finding.id} className="border-b border-[var(--border)] last:border-0">
                <td className="py-2 pr-3">{finding.rowNumber ?? "-"}</td>
                <td className="py-2 pr-3">{finding.field ?? "-"}</td>
                <td className="py-2 pr-3">{finding.errorCode}</td>
                <td className="py-2 pr-3 text-[var(--text-muted)]">{finding.message}</td>
                <td className="py-2 pr-3">
                  <SeverityBadge severity={finding.severity} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ul className="flex flex-col gap-2 sm:hidden">
        {findings.map((finding) => (
          <li key={finding.id} className="surface rounded-xl border p-3 text-sm">
            <div className="mb-1 flex items-center justify-between gap-2">
              <span className="font-medium">{finding.rowNumber != null ? `แถว ${finding.rowNumber}` : "ไฟล์"}</span>
              <SeverityBadge severity={finding.severity} />
            </div>
            {finding.field && <p className="text-[var(--text-muted)]">{finding.field}</p>}
            <p className="mt-1">{finding.message}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
