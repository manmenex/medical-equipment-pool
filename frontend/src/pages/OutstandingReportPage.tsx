import { useQuery } from "@tanstack/react-query";
import { ListSkeleton } from "@/components/Skeleton";
import { useState } from "react";

import { apiErrorMessage } from "@/services/api";
import { fetchOutstanding, fetchOutstandingLineText, type OutstandingRow } from "@/services/outstandingReport";
import "@/styles/print.css";

// Owner Governance 2026-11-28 (D30): read-only. No due date, no overdue flag,
// no notification. "มี HN" is shown on screen only; print and copy omit it.
const fmt = (iso: string) =>
  new Intl.DateTimeFormat("th-TH", {
    timeZone: "Asia/Bangkok",
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));

const device = (r: OutstandingRow) => `${r.source_badge ? `[${r.source_badge}] ` : ""}${r.equipment_name}`;

export function OutstandingReportPage() {
  const [days, setDays] = useState(7);
  const [copyMsg, setCopyMsg] = useState<string | null>(null);
  const valid = Number.isInteger(days) && days >= 1 && days <= 365;
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["reports", "outstanding", days],
    queryFn: () => fetchOutstanding(days),
    enabled: valid,
  });

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(await fetchOutstandingLineText(days));
      setCopyMsg("คัดลอกแล้ว");
    } catch {
      setCopyMsg("คัดลอกไม่สำเร็จ");
    }
  };

  return (
    <div className="print-root flex min-w-0 flex-col gap-4" data-orientation="landscape">
      <div className="no-print flex min-w-0 flex-col gap-3">
        <h1 className="text-lg font-semibold">เครื่องค้างนาน</h1>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            ค้างเกิน (วัน)
            <input
              type="number"
              min={1}
              max={365}
              value={Number.isNaN(days) ? "" : days}
              onChange={(e) => setDays(Number(e.target.value))}
              aria-label="ค้างเกิน (วัน)"
              className="w-24 rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm"
            />
          </label>
          <button onClick={copy} disabled={!valid} className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium">
            คัดลอกข้อความ LINE
          </button>
          <button onClick={() => window.print()} disabled={!valid} className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium">
            พิมพ์
          </button>
          {copyMsg && <span role="status" className="text-sm">{copyMsg}</span>}
        </div>
        {!valid && <p className="text-sm text-red-600">ใส่จำนวนวัน 1-365</p>}
        {isLoading && <ListSkeleton rows={5} rowClassName="h-9" label="กำลังโหลด..." />}
        {isError && <p className="text-sm text-red-600">{apiErrorMessage(error)}</p>}
        {data && <p className="text-sm font-medium">รวม {data.total} เครื่อง</p>}
        {data && data.total === 0 && <p className="text-sm text-[var(--text-muted)]">ไม่มีเครื่องค้าง</p>}

        {data?.wards.map((w) => (
          <section key={w.ward} className="surface rounded-xl border p-3" aria-label={w.ward}>
            <h2 className="mb-2 text-sm font-semibold">
              {w.ward} ({w.count})
            </h2>
            <div className="print-table-wrap">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr>
                    <th>BCM</th>
                    <th>เครื่อง</th>
                    <th>วันที่เบิก</th>
                    <th>ค้าง (วัน)</th>
                    <th>BME</th>
                    <th>มี HN</th>
                  </tr>
                </thead>
                <tbody>
                  {w.rows.map((r) => (
                    <tr key={r.transaction_no}>
                      <td>{r.bcm_code ?? "-"}</td>
                      <td>{device(r)}</td>
                      <td>{fmt(r.borrowed_at)}</td>
                      <td>{r.age_days}</td>
                      <td>{r.keyer ?? "-"}</td>
                      <td>{r.has_hn ? "มี HN" : "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ))}
      </div>

      {/* Print view: landscape, no HN column. */}
      {data && (
        <div className="print-only" data-testid="print-view">
          <h1 className="print-header text-lg font-semibold">
            เครื่องค้างเกิน {data.days} วัน (รวม {data.total} เครื่อง)
          </h1>
          <table className="print-table w-full text-left text-sm">
            <thead>
              <tr>
                <th>หน่วยงาน</th>
                <th>BCM</th>
                <th>เครื่อง</th>
                <th>วันที่เบิก</th>
                <th>ค้าง (วัน)</th>
                <th>BME</th>
              </tr>
            </thead>
            <tbody>
              {data.wards.flatMap((w) =>
                w.rows.map((r) => (
                  <tr key={r.transaction_no}>
                    <td>{w.ward}</td>
                    <td>{r.bcm_code ?? "-"}</td>
                    <td>{device(r)}</td>
                    <td>{fmt(r.borrowed_at)}</td>
                    <td>{r.age_days}</td>
                    <td>{r.keyer ?? "-"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
