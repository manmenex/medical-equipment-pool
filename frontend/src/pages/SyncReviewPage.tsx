import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { OtherUsersOutboxPanel } from "@/components/OtherUsersOutboxPanel";
import { canReviewSyncConflicts, useAuth } from "@/hooks/useAuth";
import { apiErrorCode, apiErrorMessage } from "@/services/api";
import {
  applySyncConflictNow,
  dismissSyncConflict,
  fetchSyncConflicts,
  type DismissReason,
  type SyncConflictItem,
} from "@/services/syncReview";
import { DISMISS_REASON_LABELS, opTypeLabel, resultCodeLabel } from "@/utils/syncReviewLabels";

export const SYNC_CONFLICTS_KEY = ["sync-conflicts"] as const;

type Pending = { kind: "dismiss" | "apply"; item: SyncConflictItem } | null;

function fmt(iso: string | null): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "-" : d.toLocaleString("th-TH");
}

export function SyncReviewPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const allowed = canReviewSyncConflicts(user);
  const query = useQuery({
    queryKey: SYNC_CONFLICTS_KEY,
    queryFn: () => fetchSyncConflicts({ limit: 100 }),
    enabled: allowed,
  });
  const [pending, setPending] = useState<Pending>(null);
  const [reason, setReason] = useState<DismissReason | "">("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [messageKind, setMessageKind] = useState<"success" | "warning">("success");

  if (!allowed) {
    return <p className="p-4 text-sm">คุณไม่มีสิทธิ์เข้าถึงหน้านี้</p>;
  }

  const close = () => {
    setPending(null);
    setReason("");
    setNote("");
    setError(null);
  };

  const refresh = async () => {
    await qc.invalidateQueries({ queryKey: SYNC_CONFLICTS_KEY });
    await qc.invalidateQueries({ queryKey: ["sync-conflicts-count"] });
  };

  const submit = async () => {
    if (!pending || busy) return;
    if (pending.kind === "dismiss" && !reason) return;
    setBusy(true);
    setError(null);
    try {
      if (pending.kind === "dismiss") {
        await dismissSyncConflict(pending.item.op_id, reason as DismissReason, note.trim() || undefined);
        setMessageKind("success");
        setMessage("ปิดรายการเรียบร้อยแล้ว");
      } else {
        await applySyncConflictNow(pending.item.op_id);
        setMessageKind("success");
        setMessage("บันทึกรายการเรียบร้อยแล้ว");
      }
      close();
      await refresh();
    } catch (e) {
      const code = apiErrorCode(e);
      if (code === "SYNC_OP_NOT_RESOLVABLE") {
        setMessageKind("success");
        setMessage("รายการนี้ถูกดำเนินการไปแล้ว รีเฟรชรายการให้แล้ว");
        close();
        await refresh();
      } else if (code === "SYNC_APPLY_FAILED") {
        setMessageKind("warning");
        setMessage("ไม่สามารถบันทึกรายการได้ เงื่อนไขของอุปกรณ์เปลี่ยนไปแล้ว รายการยังรอการตรวจสอบ");
        close();
        await refresh();
      } else {
        setError(apiErrorMessage(e));
      }
    } finally {
      setBusy(false);
    }
  };

  const items = query.data?.items ?? [];

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">ตรวจสอบรายการออฟไลน์</h1>
      <OtherUsersOutboxPanel />
      {message && (
        <p
          role="status"
          data-testid="sync-review-message"
          className={`rounded-lg px-3 py-2 text-sm ${
            messageKind === "warning" ? "bg-status-repair/15 text-status-repair" : "bg-status-available/15"
          }`}
        >
          {message}
        </p>
      )}
      {query.isLoading && <p className="text-sm text-[var(--text-muted)]">กำลังโหลด...</p>}
      {query.isError && (
        <p role="alert" className="text-sm text-status-repair">
          {apiErrorMessage(query.error)}
        </p>
      )}
      {query.data && items.length === 0 && <p className="text-sm text-[var(--text-muted)]">ไม่มีรายการที่รอตรวจสอบ</p>}
      {query.data && query.data.total > items.length && (
        <p className="text-sm text-[var(--text-muted)]">
          แสดง {items.length} จาก {query.data.total} รายการ
        </p>
      )}
      <ul className="space-y-3">
        {items.map((item) => {
          const adminOnly = item.admin_only && user?.role !== "administrator";
          return (
            <li key={item.op_id} className="surface rounded-xl border p-3 text-sm" data-testid="sync-review-item">
              <div className="flex flex-wrap items-center gap-2 font-medium">
                <span>{opTypeLabel(item.op_type)}</span>
                <span>{item.equipment?.bcm_code ?? "-"}</span>
                {item.result_code && (
                  <span className="rounded-full bg-status-repair/15 px-2 py-0.5 text-xs text-status-repair">
                    {item.result_code}
                  </span>
                )}
              </div>
              <p className="mt-1">{resultCodeLabel(item.result_code)}</p>
              <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[var(--text-muted)]">
                <dt>หน่วยงาน</dt>
                <dd>{item.ward_name ?? "-"}</dd>
                <dt>ผู้บันทึก</dt>
                <dd>{item.operator?.full_name ?? "-"}</dd>
                <dt>เวลาที่เกิดเหตุการณ์</dt>
                <dd>{fmt(item.occurred_at)}</dd>
                <dt>อุปกรณ์ (device)</dt>
                <dd>{item.device_id ?? "-"}</dd>
              </dl>
              <div className="mt-3 flex gap-2">
                <button
                  className="rounded-lg border px-3 py-1"
                  disabled={busy || adminOnly}
                  onClick={() => setPending({ kind: "dismiss", item })}
                >
                  ปิดรายการ
                </button>
                <button
                  className="rounded-lg bg-status-borrowed px-3 py-1 text-white"
                  disabled={busy || adminOnly}
                  onClick={() => setPending({ kind: "apply", item })}
                >
                  บันทึกทันที
                </button>
              </div>
            </li>
          );
        })}
      </ul>

      {pending && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={pending.kind === "dismiss" ? "ยืนยันการปิดรายการ" : "ยืนยันการบันทึกทันที"}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
        >
          <div className="surface w-full max-w-md space-y-3 rounded-xl border p-4 text-sm">
            <h2 className="font-semibold">
              {pending.kind === "dismiss" ? "ปิดรายการโดยไม่บันทึก" : "บันทึกรายการทันที"}
            </h2>
            <p>
              {opTypeLabel(pending.item.op_type)} {pending.item.equipment?.bcm_code ?? ""}
            </p>
            {pending.kind === "dismiss" ? (
              <>
                <label className="block">
                  เหตุผล
                  <select
                    className="mt-1 w-full rounded-lg border p-2"
                    value={reason}
                    onChange={(e) => setReason(e.target.value as DismissReason | "")}
                  >
                    <option value="">เลือกเหตุผล</option>
                    {Object.entries(DISMISS_REASON_LABELS).map(([v, l]) => (
                      <option key={v} value={v}>
                        {l}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  หมายเหตุ (ไม่บังคับ)
                  <textarea
                    className="mt-1 w-full rounded-lg border p-2"
                    maxLength={500}
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                  />
                </label>
              </>
            ) : (
              <>
                <p>ระบบจะบันทึกรายการนี้เป็นรายการใหม่ตามข้อมูลที่ส่งมา ยืนยันหรือไม่</p>
                <p>
                  เวลาที่จะบันทึก:{" "}
                  {pending.item.result_code === "OP_TOO_OLD" ? fmt(pending.item.occurred_at) : "เวลาปัจจุบัน"}
                </p>
              </>
            )}
            {error && (
              <p role="alert" className="text-status-repair">
                {error}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <button className="rounded-lg border px-3 py-1" disabled={busy} onClick={close}>
                ยกเลิก
              </button>
              <button
                className="rounded-lg bg-status-borrowed px-3 py-1 text-white"
                disabled={busy || (pending.kind === "dismiss" && !reason)}
                onClick={() => void submit()}
              >
                {busy ? "กำลังดำเนินการ..." : "ยืนยัน"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
