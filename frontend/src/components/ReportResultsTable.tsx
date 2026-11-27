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

const SOURCE_PREFIX: Record<string, string> = { demo: "[DEMO] ", loan: "[ยืม] " };

// dd/mm/yyyy HH:MM in Asia/Bangkok (the hospital's local time, never the
// browser's), or "-" when the event has not happened.
export function formatBangkokDateTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Bangkok",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(d);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  return `${get("day")}/${get("month")}/${get("year")} ${get("hour")}:${get("minute")}`;
}

// Roadmap PR17 Slice 3: a single shared row/table renderer for both
// ReceiveReportPage and IssueReportPage. Renders exactly what the backend
// returns (BME keyer labels are already resolved server-side); no
// lifecycle/eligibility logic and no client-side sort. `kind` only selects
// which side's ward-contact column is shown. The table scrolls inside its
// own container, so the page itself never scrolls horizontally.
export function ReportResultsTable({
  rows,
  kind = "receive",
}: {
  rows: ReportTransactionOut[];
  kind?: "receive" | "issue";
}) {
  const { data: wards } = useQuery({ queryKey: ["wards"], queryFn: listWards });

  function wardName(wardId: string | null): string {
    if (!wardId) return "ไม่ทราบ";
    return wards?.find((w) => w.id === wardId)?.name ?? "ไม่ทราบ";
  }

  if (rows.length === 0) {
    return <p className="text-sm text-[var(--text-muted)]">ไม่พบรายการ</p>;
  }

  const th = "py-2 pr-3 font-medium";
  const contactHeader = kind === "issue" ? "ผู้รับ (Ward)" : "ผู้ส่งคืน (Ward)";

  return (
    <div className="max-w-full overflow-x-auto">
      <table className="w-full min-w-[960px] text-left text-xs">
        <thead>
          <tr className="border-b border-[var(--border)] text-[var(--text-muted)]">
            <th scope="col" className={th}>
              เลขที่รายการ
            </th>
            <th scope="col" className={th}>
              รหัส
            </th>
            <th scope="col" className={th}>
              เครื่องมือ
            </th>
            <th scope="col" className={th}>
              Ward
            </th>
            <th scope="col" className={th}>
              {contactHeader}
            </th>
            <th scope="col" className={th}>
              เบิกโดย
            </th>
            <th scope="col" className={th}>
              วันที่/เวลาเบิก
            </th>
            <th scope="col" className={th}>
              รับคืนโดย
            </th>
            <th scope="col" className={th}>
              วันที่/เวลารับคืน
            </th>
            <th scope="col" className={th}>
              สภาพเมื่อรับคืน
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const contact = kind === "issue" ? row.dispatch_contact_name : row.receipt_contact_name;
            return (
              <tr key={row.id} className="border-b border-[var(--border)] align-top last:border-0">
                <td className="whitespace-nowrap py-2 pr-3">{row.transaction_no}</td>
                <td className="whitespace-nowrap py-2 pr-3">{row.equipment.bcm_code || row.equipment.asset_number || "-"}</td>
                <td className="py-2 pr-3">
                  {SOURCE_PREFIX[row.equipment.equipment_source ?? "pool"] ?? ""}
                  {row.equipment.equipment_name}
                  {row.category_name && <div className="text-[var(--text-muted)]">{row.category_name}</div>}
                </td>
                <td className="py-2 pr-3">{wardName(row.ward_id)}</td>
                <td className="py-2 pr-3">{contact ?? "-"}</td>
                <td className="py-2 pr-3">{row.dispatch_operator_display_name ?? "-"}</td>
                <td className="whitespace-nowrap py-2 pr-3">
                  {formatBangkokDateTime(row.borrowed_at)}
                  <div className="text-[var(--text-muted)]">{SHIFT_LABELS[row.dispatch_shift]}</div>
                </td>
                <td className="py-2 pr-3">{row.receipt_operator_display_name ?? "-"}</td>
                <td className="whitespace-nowrap py-2 pr-3">
                  {formatBangkokDateTime(row.returned_at)}
                  {row.receipt_shift && (
                    <div className="text-[var(--text-muted)]">{SHIFT_LABELS[row.receipt_shift as Shift]}</div>
                  )}
                </td>
                <td className="py-2 pr-3">
                  {row.receipt_outcome ? RECEIPT_OUTCOME_LABELS[row.receipt_outcome] ?? row.receipt_outcome : "-"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
