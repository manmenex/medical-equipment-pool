import { useQuery } from "@tanstack/react-query";

import { listWards } from "@/services/masterData";
import type { ReportTransactionOut, Shift } from "@/types";

const SHIFT_LABELS: Record<Shift, string> = {
  day: "กลางวัน",
  night: "กลางคืน",
};

const RECEIPT_OUTCOME_LABELS: Record<string, string> = {
  usable: "ใช้งานได้",
  defective: "ชำรุด",
};

// Roadmap PR17 Slice 3: a single shared row/table renderer for both
// ReceiveReportPage and IssueReportPage -- ReportTransactionOut already
// carries every field either screen needs, so one component avoids
// duplicating table markup between them. Renders exactly what the backend
// returns; no lifecycle/eligibility logic, no client-side sort, no
// timestamp derivation of any kind (docs/design/
// PR17_OPERATIONAL_REPORTS_PLAN.md §8/§11 -- "the report endpoints already
// return only valid rows").
export function ReportResultsTable({ rows }: { rows: ReportTransactionOut[] }) {
  const { data: wards } = useQuery({ queryKey: ["wards"], queryFn: listWards });

  function wardName(wardId: string | null): string {
    if (!wardId) return "ไม่ทราบ";
    return wards?.find((w) => w.id === wardId)?.name ?? "ไม่ทราบ";
  }

  if (rows.length === 0) {
    return <p className="text-sm text-[var(--text-muted)]">ไม่พบรายการ</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-left text-sm">
        <thead>
          <tr className="border-b border-[var(--border)] text-xs text-[var(--text-muted)]">
            <th scope="col" className="py-2 pr-3 font-medium">
              เลขที่รายการ
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              เครื่องมือ
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              หอผู้ป่วย
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              เบิกโดย
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              วันที่ทำการเบิก / กะ
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              รับคืนโดย
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              วันที่ทำการรับคืน / กะ
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              สภาพเมื่อรับคืน
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-b border-[var(--border)] last:border-0">
              <td className="py-2 pr-3">{row.transaction_no}</td>
              <td className="py-2 pr-3">
                {row.equipment.equipment_name}
                <div className="text-xs text-[var(--text-muted)]">{row.equipment.asset_number}</div>
              </td>
              <td className="py-2 pr-3">{wardName(row.ward_id)}</td>
              <td className="py-2 pr-3">{row.dispatch_operator_display_name ?? "-"}</td>
              <td className="py-2 pr-3">
                {row.dispatch_business_date} · {SHIFT_LABELS[row.dispatch_shift]}
              </td>
              <td className="py-2 pr-3">{row.receipt_operator_display_name ?? "-"}</td>
              <td className="py-2 pr-3">
                {row.receipt_business_date ? `${row.receipt_business_date} · ${SHIFT_LABELS[row.receipt_shift as Shift]}` : "-"}
              </td>
              <td className="py-2 pr-3">
                {row.receipt_outcome ? RECEIPT_OUTCOME_LABELS[row.receipt_outcome] ?? row.receipt_outcome : "-"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
