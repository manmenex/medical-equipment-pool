import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { apiErrorCode, apiErrorMessage } from "@/services/api";
import { applySequence, fetchEquipmentTimeline, type TimelineEvent } from "@/services/syncSequence";
import { opTypeLabel, resultCodeLabel } from "@/utils/syncReviewLabels";

function fmt(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "-" : d.toLocaleString("th-TH");
}

interface Props {
  equipmentId: string;
  onClose: () => void;
  /** Called after any apply attempt so the review list can refresh. */
  onChanged: () => void | Promise<void>;
}

/** PR25E B4b (D7): per-equipment timeline with selectable ops and a
 *  human-confirmed "Apply sequence". Nothing is applied automatically. */
export function SyncTimelinePanel({ equipmentId, onClose, onChanged }: Props) {
  const query = useQuery({
    queryKey: ["sync-timeline", equipmentId],
    queryFn: () => fetchEquipmentTimeline(equipmentId),
  });
  // Selection order = the order the resolver ticks; the dialog shows it.
  const [selected, setSelected] = useState<string[]>([]);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  const events = query.data?.events ?? [];
  const byOp = new Map(events.filter((e) => e.op_id).map((e) => [e.op_id as string, e]));
  // Apply in timeline (corrected-time) order, not click order.
  const ordered = events.filter((e) => e.op_id && selected.includes(e.op_id));

  const toggle = (id: string) =>
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  const confirm = async () => {
    if (busy || ordered.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const out = await applySequence(
        equipmentId,
        ordered.map((e) => e.op_id as string),
      );
      setResult(
        out.failed
          ? `บันทึกแล้ว ${out.steps.length} รายการ และหยุดที่รายการที่ ${out.steps.length + 1} (${out.failed.code ?? ""}) ที่เหลือยังรอการตรวจสอบ`
          : `บันทึกครบ ${out.steps.length} รายการเรียบร้อยแล้ว`,
      );
      setConfirming(false);
      setSelected([]);
      await onChanged();
      await query.refetch();
    } catch (e) {
      const code = apiErrorCode(e);
      if (code === "SYNC_OP_NOT_RESOLVABLE" || code === "SYNC_APPLY_FAILED") {
        setResult("ไม่สามารถบันทึกลำดับได้ รายการถูกดำเนินการไปแล้วหรือเงื่อนไขของอุปกรณ์เปลี่ยนไป รีเฟรชข้อมูลแล้ว");
        setConfirming(false);
        setSelected([]);
        await onChanged();
        await query.refetch();
      } else {
        setError(apiErrorMessage(e));
      }
    } finally {
      setBusy(false);
    }
  };

  const label = (e: TimelineEvent) =>
    e.source === "transaction"
      ? `${opTypeLabel(e.kind)} (บันทึกแล้ว)`
      : `${opTypeLabel(e.kind)} (รอตรวจสอบ)`;

  return (
    <section className="surface space-y-3 rounded-xl border p-3 text-sm" aria-label="ลำดับเหตุการณ์">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">
          ลำดับเหตุการณ์ {query.data?.equipment.bcm_code ?? ""} {query.data?.equipment.equipment_name ?? ""}
        </h2>
        <button className="rounded-lg border px-3 py-1" onClick={onClose}>
          ปิดลำดับเหตุการณ์
        </button>
      </div>
      {query.isLoading && <p className="text-[var(--text-muted)]">กำลังโหลด...</p>}
      {query.isError && (
        <p role="alert" className="text-status-repair">
          {apiErrorMessage(query.error)}
        </p>
      )}
      {result && (
        <p role="status" className="rounded-lg bg-status-available/15 px-3 py-2">
          {result}
        </p>
      )}
      <ol className="space-y-2">
        {events.map((e, i) => (
          <li key={`${e.op_id ?? e.transaction_id}-${e.kind}-${i}`} className="rounded-lg border p-2" data-testid="timeline-event">
            <div className="flex flex-wrap items-center gap-2">
              {e.selectable && e.op_id && (
                <input
                  type="checkbox"
                  aria-label={`เลือก ${opTypeLabel(e.kind)} ${fmt(e.at)}`}
                  checked={selected.includes(e.op_id)}
                  disabled={busy}
                  onChange={() => toggle(e.op_id as string)}
                />
              )}
              <span className="font-medium">{label(e)}</span>
              <span>{fmt(e.at)}</span>
              {e.order_uncertain && (
                <span className="rounded-full bg-status-repair/15 px-2 py-0.5 text-xs text-status-repair">
                  ลำดับไม่แน่ชัด
                </span>
              )}
              {e.stale_context && <span className="rounded-full border px-2 py-0.5 text-xs">ข้อมูลเก่า</span>}
            </div>
            <p className="text-[var(--text-muted)]">
              {e.operator?.full_name ?? "-"} / {e.ward_name ?? "-"}
              {e.receipt_outcome ? ` / ${e.receipt_outcome}` : ""}
            </p>
            {e.source === "op" && <p>{resultCodeLabel(e.result_code ?? null)}</p>}
          </li>
        ))}
      </ol>
      {query.data && events.length === 0 && <p className="text-[var(--text-muted)]">ไม่มีเหตุการณ์</p>}
      <button
        className="rounded-lg bg-status-borrowed px-3 py-1 text-white"
        disabled={busy || ordered.length === 0}
        onClick={() => setConfirming(true)}
      >
        Apply sequence ({ordered.length})
      </button>

      {confirming && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="ยืนยัน Apply sequence"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
        >
          <div className="surface w-full max-w-md space-y-3 rounded-xl border p-4 text-sm">
            <h3 className="font-semibold">บันทึกตามลำดับต่อไปนี้</h3>
            <ol className="list-decimal space-y-1 pl-5">
              {ordered.map((e) => (
                <li key={e.op_id}>
                  {opTypeLabel(e.kind)} {fmt(e.at)} {byOp.get(e.op_id as string)?.operator?.full_name ?? ""}
                </li>
              ))}
            </ol>
            <p>ระบบจะบันทึกทีละรายการตามลำดับนี้ และหยุดทันทีที่รายการใดบันทึกไม่ได้ รายการที่เหลือจะยังรอการตรวจสอบ ยืนยันหรือไม่</p>
            {error && (
              <p role="alert" className="text-status-repair">
                {error}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <button className="rounded-lg border px-3 py-1" disabled={busy} onClick={() => setConfirming(false)}>
                ยกเลิก
              </button>
              <button
                className="rounded-lg bg-status-borrowed px-3 py-1 text-white"
                disabled={busy}
                onClick={() => void confirm()}
              >
                {busy ? "กำลังดำเนินการ..." : "ยืนยัน"}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
