import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { apiErrorMessage } from "@/services/api";
import { downloadCollisionCsv, fetchCollisionStats } from "@/services/syncSequence";

function pct(v: number | null): string {
  return v === null ? "-" : `${(v * 100).toFixed(1)}%`;
}

/** PR25E B4b (D8): statistics feeding the post-pilot decision on automatic
 *  sequencing, which is NOT enabled in v1. Administrators only. */
export function SyncStatsPanel() {
  const query = useQuery({ queryKey: ["sync-collision-stats"], queryFn: fetchCollisionStats });
  const [error, setError] = useState<string | null>(null);

  const download = async () => {
    setError(null);
    try {
      await downloadCollisionCsv();
    } catch (e) {
      setError(apiErrorMessage(e));
    }
  };

  const s = query.data;
  return (
    <section className="surface space-y-2 rounded-xl border p-3 text-sm" aria-label="สถิติรายการชนกัน">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">สถิติรายการที่ขัดแย้ง (30 วัน)</h2>
        <button className="rounded-lg border px-3 py-1" onClick={() => void download()}>
          ดาวน์โหลด CSV
        </button>
      </div>
      {query.isError && (
        <p role="alert" className="text-status-repair">
          {apiErrorMessage(query.error)}
        </p>
      )}
      {error && (
        <p role="alert" className="text-status-repair">
          {error}
        </p>
      )}
      {s && (
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
          <dt>รายการขัดแย้งทั้งหมด</dt>
          <dd>{s.total_conflicts}</dd>
          <dt>เครื่องที่ขัดแย้งหลายรายการ</dt>
          <dd>{s.groups.equipment_with_multiple_conflicts}</dd>
          <dt>ข้ามอุปกรณ์ (device)</dt>
          <dd>{s.groups.cross_device}</dd>
          <dt>ตัดสินตามลำดับเวลา</dt>
          <dd>{pct(s.groups.agreement_rate)}</dd>
          <dt>เข้าเงื่อนไขจัดลำดับอัตโนมัติ</dt>
          <dd>
            {s.groups.would_have_auto_sequenced.conditions_met} (ตรงกัน{" "}
            {s.groups.would_have_auto_sequenced.resolved_same_order})
          </dd>
          {Object.entries(s.by_result_code).map(([code, n]) => (
            <div key={code} className="contents">
              <dt>{code}</dt>
              <dd>{n}</dd>
            </div>
          ))}
        </dl>
      )}
      {s?.truncated && <p className="text-[var(--text-muted)]">ข้อมูลถูกตัดตามขีดจำกัด</p>}
    </section>
  );
}
