import { useEffect, useMemo, useState } from "react";

import { OfflineStaleGate } from "@/components/OfflineStaleGate";
import {
  enqueueOfflineReceipt,
  listReceiptCandidates,
  LocalOpError,
  rankBcmMatches,
  stripBcmPrefix,
  type ReceiptCandidate,
} from "@/offline/localOps";
import { OfflineStoreError } from "@/offline/offlineStore";
import type { ReceiptOutcome } from "@/types";

const OUTCOMES: { value: ReceiptOutcome; label: string; selectedClass: string }[] = [
  { value: "usable", label: "พร้อมใช้งาน", selectedClass: "border-status-available bg-status-available/10" },
  { value: "defective", label: "ชำรุด", selectedClass: "border-status-repair bg-status-repair/10" },
];

// PR25E S4 (design 3.1, D7): offline receipt. The operator picks from open
// transactions cached in the snapshot plus this user's own unsent offline
// dispatches; the operation is addressed by transaction_id only. QR scanning
// is online only (D1).
export function OfflineReceiptForm() {
  const [candidates, setCandidates] = useState<ReceiptCandidate[] | null>(null);
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<ReceiptCandidate | null>(null);
  const [outcome, setOutcome] = useState<ReceiptOutcome>("usable");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const load = () =>
    listReceiptCandidates()
      .then(setCandidates)
      .catch(() => {
        setCandidates([]);
        setError("อ่านข้อมูลที่เก็บไว้ในเครื่องไม่ได้");
      });
  useEffect(() => {
    void load();
  }, []);

  const shown = useMemo(() => {
    if (!candidates) return [];
    if (!stripBcmPrefix(filter)) return candidates;
    const ids = new Set(rankBcmMatches(candidates, filter, 50).map((c) => c.transaction_id));
    return candidates.filter((c) => ids.has(c.transaction_id));
  }, [candidates, filter]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selected) return;
    setSubmitting(true);
    setError(null);
    try {
      await enqueueOfflineReceipt({
        transaction_id: selected.transaction_id,
        receipt_outcome: outcome,
        notes: notes || undefined,
      });
      setSaved(true);
    } catch (err) {
      setError(
        err instanceof LocalOpError || err instanceof OfflineStoreError ? err.message : "บันทึกในเครื่องไม่สำเร็จ",
      );
    } finally {
      setSubmitting(false);
    }
  };

  if (saved) {
    return (
      <div className="surface mx-auto mt-8 max-w-sm rounded-xl border p-6 text-center">
        <div className="mb-2 text-4xl">🕓</div>
        <h2 className="text-lg font-semibold">บันทึกในเครื่องแล้ว — ยังไม่ได้ส่งเข้าระบบ</h2>
        <p className="mt-1 text-sm text-[var(--text-muted)]">ระบบจะส่งอัตโนมัติเมื่อเชื่อมต่อเซิร์ฟเวอร์ได้</p>
        <button
          onClick={() => {
            setSaved(false);
            setSelected(null);
            setNotes("");
            setOutcome("usable");
            void load();
          }}
          className="mt-4 rounded-lg bg-status-available px-4 py-2 text-sm font-medium text-white"
        >
          รับคืนเครื่องถัดไป
        </button>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-sm flex-col gap-4">
      <OfflineStaleGate />
      <h1 className="text-lg font-semibold">รับคืนเครื่องมือ</h1>
      <p className="text-sm text-[var(--text-muted)]">
        เซิร์ฟเวอร์ไม่พร้อมใช้งาน — เลือกรายการเบิกที่ค้างอยู่ (สแกน QR ใช้ได้เฉพาะตอนออนไลน์)
      </p>
      {!selected ? (
        <>
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="กรอกรหัส BCM"
            aria-label="ค้นหารหัส BCM"
            autoComplete="off"
            className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
          />
          {candidates && shown.length === 0 && (
            <p className="text-sm text-[var(--text-muted)]">ไม่พบรายการเบิกที่ค้างอยู่ในเครื่อง</p>
          )}
          <ul className="flex flex-col gap-2">
            {shown.map((c) => (
              <li key={c.transaction_id}>
                <button
                  type="button"
                  onClick={() => setSelected(c)}
                  className="surface w-full rounded-lg border p-3 text-left text-sm"
                >
                  <div className="font-medium">{c.bcm_code ?? "-"}</div>
                  <div className="text-[var(--text-muted)]">
                    {c.equipment_name}
                    {c.ward_name ? ` · ${c.ward_name}` : ""}
                  </div>
                  {c.source === "local" && (
                    <div className="text-xs text-status-borrowed">เบิกในเครื่องนี้ (ยังไม่ได้ส่ง)</div>
                  )}
                </button>
              </li>
            ))}
          </ul>
          {error && <p className="text-sm text-status-repair">{error}</p>}
        </>
      ) : (
        <form onSubmit={submit} className="flex flex-col gap-4">
          <div className="surface rounded-xl border p-4">
            <div className="font-medium">{selected.bcm_code ?? "-"}</div>
            <div className="text-sm text-[var(--text-muted)]">{selected.equipment_name}</div>
            <button type="button" onClick={() => setSelected(null)} className="mt-2 text-xs underline">
              เลือกรายการอื่น
            </button>
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">สภาพเครื่องเมื่อรับคืน</label>
            <div className="grid grid-cols-2 gap-2">
              {OUTCOMES.map((o) => (
                <label
                  key={o.value}
                  className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
                    outcome === o.value ? o.selectedClass : "border-[var(--border)]"
                  }`}
                >
                  <input
                    type="radio"
                    name="receipt_outcome"
                    value={o.value}
                    checked={outcome === o.value}
                    onChange={() => setOutcome(o.value)}
                  />
                  {o.label}
                </label>
              ))}
            </div>
          </div>
          <div>
            <label htmlFor="offline-receipt-notes" className="mb-1 block text-sm font-medium">
              หมายเหตุ
            </label>
            <textarea
              id="offline-receipt-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
              rows={2}
            />
          </div>
          {error && <p className="text-sm text-status-repair">{error}</p>}
          <button
            type="submit"
            disabled={submitting}
            className="rounded-lg bg-status-available py-2.5 font-medium text-white disabled:opacity-60"
          >
            {submitting ? "กำลังบันทึก..." : "บันทึกการรับคืน (ในเครื่อง)"}
          </button>
        </form>
      )}
    </div>
  );
}
