import { useEffect, useRef, useState } from "react";

import { apiErrorCode, apiErrorMessage } from "@/services/api";
import { WARD_CORRECTION_REASON_MAX_LENGTH, correctTransactionWard, getTransaction } from "@/services/borrow";
import type { TransactionOut, Ward, WardCorrectionErrorCode } from "@/types";

interface WardCorrectionDialogProps {
  transaction: TransactionOut;
  wards: Ward[];
  onClose: () => void;
  // Called both on a successful correction and after a conflict-triggered
  // refresh -- either way the caller has a fresh, server-confirmed
  // TransactionOut and a Thai message describing what happened.
  onUpdated: (updated: TransactionOut, message: string) => void;
}

// Roadmap PR9A's exact codes for this endpoint (docs/api/transactions.md,
// docs/api/ERROR_CODES.md) -- WARD_CORRECTION_CONFLICT is deliberately
// absent here: it is handled separately (see handleSubmit) because it
// requires refetching the transaction, not just showing a message.
const WARD_CORRECTION_ERROR_MESSAGES: Partial<Record<WardCorrectionErrorCode, string>> = {
  FORBIDDEN: "คุณไม่มีสิทธิ์แก้ไขแผนกรับเครื่อง",
  TRANSACTION_NOT_FOUND: "ไม่พบรายการนี้แล้ว อาจมีการเปลี่ยนแปลงไปก่อนหน้านี้",
  INVALID_INPUT: "หอผู้ป่วยที่เลือกไม่ถูกต้อง กรุณาโหลดรายชื่อหอผู้ป่วยใหม่แล้วลองอีกครั้ง",
  WARD_CORRECTION_NOOP: "หอผู้ป่วยที่เลือกตรงกับข้อมูลปัจจุบันอยู่แล้ว จึงไม่มีการเปลี่ยนแปลง",
  VALIDATION_ERROR: "ข้อมูลไม่ถูกต้อง กรุณาตรวจสอบแล้วลองอีกครั้ง",
};

const CONFLICT_MESSAGE =
  "มีคำขอแก้ไขแผนกอื่นดำเนินการสำเร็จก่อนคำขอนี้ ระบบได้แสดงข้อมูลล่าสุดให้แล้ว กรุณาตรวจสอบแล้วลองอีกครั้งหากต้องการ";

function getFocusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )
  );
}

export function WardCorrectionDialog({ transaction, wards, onClose, onUpdated }: WardCorrectionDialogProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [wardId, setWardId] = useState("");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    panelRef.current?.focus();
  }, []);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        if (!submitting) onClose();
        return;
      }
      if (e.key === "Tab" && panelRef.current) {
        const focusable = getFocusableElements(panelRef.current);
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [submitting, onClose]);

  // The currently recorded ward is excluded from the selectable list
  // entirely -- this is what guarantees a same-ward correction can never be
  // submitted from this UI (the backend's own WARD_CORRECTION_NOOP guard
  // remains authoritative regardless).
  const currentWard = wards.find((w) => w.id === transaction.ward_id);
  const selectableWards = wards.filter((w) => w.id !== transaction.ward_id);
  const selectedWard = wards.find((w) => w.id === wardId);

  const trimmedReason = reason.trim();
  const reasonTooLong = trimmedReason.length > WARD_CORRECTION_REASON_MAX_LENGTH;
  const canSubmit = Boolean(wardId) && trimmedReason.length > 0 && !reasonTooLong && !submitting;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const updated = await correctTransactionWard(transaction.id, { ward_id: wardId, reason: trimmedReason });
      onUpdated(updated, "แก้ไขแผนกรับเครื่องสำเร็จ");
      return;
    } catch (err) {
      const code = apiErrorCode(err) as WardCorrectionErrorCode | undefined;
      if (code === "WARD_CORRECTION_CONFLICT") {
        try {
          const refreshed = await getTransaction(transaction.id);
          onUpdated(refreshed, CONFLICT_MESSAGE);
          return;
        } catch (refreshErr) {
          setError(apiErrorMessage(refreshErr, "แก้ไขแผนกรับเครื่องไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"));
          setSubmitting(false);
          return;
        }
      }
      const knownMessage = code ? WARD_CORRECTION_ERROR_MESSAGES[code] : undefined;
      setError(knownMessage ?? apiErrorMessage(err, "แก้ไขแผนกรับเครื่องไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"));
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-4 sm:items-center"
      onClick={() => !submitting && onClose()}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="ward-correction-title"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className="surface flex w-full max-w-sm flex-col gap-3 rounded-xl border p-4 outline-none"
      >
        <h2 id="ward-correction-title" className="text-base font-semibold">
          ยืนยันการแก้ไขแผนกรับเครื่อง
        </h2>

        <div className="rounded-lg bg-[var(--border)]/20 p-3 text-sm">
          <div className="font-medium">{transaction.equipment.equipment_name}</div>
          <div className="text-[var(--text-muted)]">
            {transaction.equipment.asset_number}
            {transaction.transaction_no ? ` · เลขที่รายการ ${transaction.transaction_no}` : ""}
          </div>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div>
            <span className="mb-1 block text-sm font-medium">แผนกที่บันทึกไว้ปัจจุบัน</span>
            <p className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm">
              {currentWard?.name ?? "ไม่ทราบ"}
            </p>
          </div>

          <div>
            <label htmlFor="ward-correction-ward" className="mb-1 block text-sm font-medium">
              แผนกที่ถูกต้อง *
            </label>
            <select
              id="ward-correction-ward"
              required
              value={wardId}
              onChange={(e) => setWardId(e.target.value)}
              disabled={submitting}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-3 text-base"
            >
              <option value="">- เลือกแผนก -</option>
              {selectableWards.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
            {selectedWard && (
              <p className="mt-1 text-sm text-[var(--text-muted)]">
                จะเปลี่ยนจาก <strong>{currentWard?.name ?? "ไม่ทราบ"}</strong> เป็น{" "}
                <strong>{selectedWard.name}</strong>
              </p>
            )}
          </div>

          <div>
            <label htmlFor="ward-correction-reason" className="mb-1 block text-sm font-medium">
              เหตุผลในการแก้ไข *
            </label>
            <textarea
              id="ward-correction-reason"
              required
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              disabled={submitting}
              rows={3}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
            />
            <p
              className={`mt-1 text-xs ${reasonTooLong ? "font-medium text-status-repair" : "text-[var(--text-muted)]"}`}
            >
              {trimmedReason.length}/{WARD_CORRECTION_REASON_MAX_LENGTH} ตัวอักษร
              {reasonTooLong ? " — เกินจำนวนที่กำหนด กรุณาแก้ไขให้สั้นลง" : ""}
            </p>
          </div>

          <div className="rounded-lg border border-[var(--border)] bg-[var(--border)]/10 p-3 text-sm">
            การดำเนินการนี้จะแก้ไขแผนกรับเครื่องที่บันทึกไว้เดิม และจะถูกบันทึกในประวัติการตรวจสอบ
            ไม่ใช่การบันทึกการย้ายเครื่องระหว่างแผนก
          </div>

          {error && (
            <p role="alert" className="text-sm text-status-repair">
              {error}
            </p>
          )}

          <div className="mt-1 flex gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="flex-1 rounded-lg border border-[var(--border)] py-2.5 font-medium disabled:opacity-60"
            >
              ยกเลิก
            </button>
            <button
              type="submit"
              disabled={!canSubmit}
              className="flex-1 rounded-lg bg-status-borrowed py-2.5 font-medium text-white disabled:opacity-60"
            >
              {submitting ? "กำลังบันทึก..." : "ยืนยันการแก้ไข"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
