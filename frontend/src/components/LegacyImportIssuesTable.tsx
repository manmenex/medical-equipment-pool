import type { ImportIssue } from "@/types/legacyImport";
import { IMPORT_ISSUE_SEVERITY_COLORS, IMPORT_ISSUE_SEVERITY_LABELS } from "@/utils/legacyImportLabels";

function SeverityBadge({ severity }: { severity: ImportIssue["severity"] }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${IMPORT_ISSUE_SEVERITY_COLORS[severity]}`}>
      {IMPORT_ISSUE_SEVERITY_LABELS[severity]}
    </span>
  );
}

// PR19B "Row-level issues skeleton": representative mock rows only. Renders
// a table on wider screens and a stacked-card fallback on small screens
// (task brief, Accessibility: "responsive tables or card fallback on small
// screens").
export function LegacyImportIssuesTable({ issues }: { issues: ImportIssue[] }) {
  if (issues.length === 0) {
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
                ค่าที่ส่งมา
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
            {issues.map((issue) => (
              <tr key={`${issue.rowNumber}-${issue.field}`} className="border-b border-[var(--border)] last:border-0">
                <td className="py-2 pr-3">{issue.rowNumber}</td>
                <td className="py-2 pr-3">{issue.field}</td>
                <td className="py-2 pr-3">{issue.submittedValue}</td>
                <td className="py-2 pr-3 text-[var(--text-muted)]">{issue.explanationTh}</td>
                <td className="py-2 pr-3">
                  <SeverityBadge severity={issue.severity} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ul className="flex flex-col gap-2 sm:hidden">
        {issues.map((issue) => (
          <li key={`${issue.rowNumber}-${issue.field}`} className="surface rounded-xl border p-3 text-sm">
            <div className="mb-1 flex items-center justify-between gap-2">
              <span className="font-medium">แถว {issue.rowNumber}</span>
              <SeverityBadge severity={issue.severity} />
            </div>
            <p className="text-[var(--text-muted)]">
              {issue.field}: {issue.submittedValue}
            </p>
            <p className="mt-1">{issue.explanationTh}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
