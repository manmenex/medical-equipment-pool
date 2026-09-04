import { useEffect, useRef, useState } from "react";

import { apiErrorCode, apiErrorMessage } from "@/services/api";
import { updateReconciliationFindingDisposition } from "@/services/reconciliation";
import type {
  ReconciliationDisposition,
  ReconciliationFindingDetail,
  ReconciliationFindingErrorCode,
} from "@/types/reconciliation";
import { RECONCILIATION_DISPOSITION_LABELS, reconciliationFindingCodeLabel } from "@/utils/reconciliationLabels";

interface ReconciliationDispositionDialogProps {
  finding: ReconciliationFindingDetail;
  onClose: () => void;
  // Called on a successful mutation AND on SIGNED_OFF/VERSION_CONFLICT
  // conflicts that require a refetch -- the caller always refetches
  // finding/run/findings-list state on this callback, mirroring
  // WardCorrectionDialog's onUpdated contract.
  onSettled: (message: string) => void;
  triggerRef?: React.RefObject<HTMLElement | null>;
}

// Exactly the four OD-PR22-2 values (§19 of the task) -- never
// "confirmed_pair", never a fifth option.
const DISPOSITION_OPTIONS: ReconciliationDisposition[] = [
  "confirmed_valid",
  "confirmed_duplicate",
  "accepted_unresolved",
  "requires_correction",
];

const NOTE_MAX_LENGTH = 4000;

// Roadmap PR22D's exact public codes for this endpoint
// (docs/api/ERROR_CODES.md) -- VERSION_CONFLICT and SIGNED_OFF are
// handled separately in handleSubmit (§21/§22 of the task: both require
// a refetch, not just a message).
const DISPOSITION_ERROR_MESSAGES: Partial<Record<ReconciliationFindingErrorCode, string>> = {
  RECONCILIATION_RUN_NOT_FOUND: "ไม่พบรอบการตรวจสอบของรายการนี้แล้ว อาจมีการเปลี่ยนแปลงไปก่อนหน้านี้",
  RECONCILIATION_FINDING_NOT_FOUND: "ไม่พบรายการนี้แล้ว อาจมีการเปลี่ยนแปลงไปก่อนหน้านี้",
  RECONCILIATION_FINDING_RUN_NOT_COMPLETED: "รอบการตรวจสอบของรายการนี้ยังไม่เสร็จสิ้นการประมวลผล จึงยังไม่สามารถบันทึกผลการตรวจได้",
};

const VERSION_CONFLICT_MESSAGE =
  "ข้อมูลรายการนี้ถูกแก้ไขโดยผู้ใช้อื่น กรุณาโหลดข้อมูลล่าสุดก่อนดำเนินการอีกครั้ง";
const SIGNED_OFF_MESSAGE = "รายการตรวจสอบนี้ถูกลงนามยืนยันแล้ว จึงไม่สามารถแก้ไขผลการตรวจสอบได้";

function getFocusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )
  );
}

// Roadmap PR22F §18-22 of the task -- the Administrator-only disposition
// mutation dialog, mirroring WardCorrectionDialog's established
// focus-trap/keyboard/conflict pattern. Always submits the finding's own
// currently-loaded `version` as `expected_version` -- never guessed or
// incremented client-side (§18).
export function ReconciliationDispositionDialog({
  finding,
  onClose,
  onSettled,
  triggerRef,
}: ReconciliationDispositionDialogProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [disposition, setDisposition] = useState<ReconciliationDisposition | "">(finding.disposition ?? "");
  const [note, setNote] = useState(finding.disposition_note ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isRedisposition = finding.disposition != null;

  useEffect(() => {
    if (!panelRef.current) return;
    const focusable = getFocusableElements(panelRef.current);
    (focusable[0] ?? panelRef.current).focus();
  }, []);

  useEffect(() => {
    return () => {
      triggerRef?.current?.focus();
    };
  }, [triggerRef]);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        if (!submitting) onClose();
        return;
      }
      if (e.key === "Tab" && panelRef.current) {
        const focusable = getFocusableElements(panelRef.current);
        if (focusable.length === 0) {
          e.preventDefault();
          panelRef.current.focus();
          return;
        }
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        const active = document.activeElement;
        const activeIndex = active ? focusable.indexOf(active as HTMLElement) : -1;
        const focusNotContained = active === panelRef.current || activeIndex === -1;
        if (focusNotContained) {
          e.preventDefault();
          (e.shiftKey ? last : first).focus();
          return;
        }
        if (e.shiftKey && active === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [submitting, onClose]);

  const trimmedNote = note.trim();
  const noteTooLong = trimmedNote.length > NOTE_MAX_LENGTH;
  const canSubmit = Boolean(disposition) && !noteTooLong && !submitting;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit || !disposition) return;
    setSubmitting(true);
    setError(null);
    try {
      await updateReconciliationFindingDisposition(finding.id, {
        disposition,
        expected_version: finding.version,
        disposition_note: trimmedNote || null,
      });
      onSettled("บันทึกผลการตรวจสอบสำเร็จ");
      return;
    } catch (err) {
      const code = apiErrorCode(err) as ReconciliationFindingErrorCode | undefined;
      if (code === "RECONCILIATION_FINDING_VERSION_CONFLICT") {
        setError(VERSION_CONFLICT_MESSAGE);
        onSettled(VERSION_CONFLICT_MESSAGE);
        setSubmitting(false);
        return;
      }
      if (code === "RECONCILIATION_FINDING_SIGNED_OFF") {
        setError(SIGNED_OFF_MESSAGE);
        onSettled(SIGNED_OFF_MESSAGE);
        setSubmitting(false);
        return;
      }
      const knownMessage = code ? DISPOSITION_ERROR_MESSAGES[code] : undefined;
      setError(knownMessage ?? apiErrorMessage(err, "บันทึกผลการตรวจสอบไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"));
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
        aria-labelledby="reconciliation-disposition-title"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className="surface flex w-full max-w-md flex-col gap-3 rounded-xl border p-4 outline-none"
      >
        <h2 id="reconciliation-disposition-title" className="text-base font-semibold">
          บันทึกผลการตรวจสอบรายการ
        </h2>

        <div className="rounded-lg bg-[var(--border)]/20 p-3 text-sm">
          <div className="font-medium">{reconciliationFindingCodeLabel(finding.code)}</div>
          {finding.equipment && (
            <div className="text-[var(--text-muted)]">
              {finding.equipment.equipment_name} · {finding.equipment.asset_number}
            </div>
          )}
        </div>

        {isRedisposition && (
          <p className="rounded-lg border border-[var(--border)] bg-[var(--border)]/10 p-3 text-sm">
            รายการนี้เคยมีผลการตรวจสอบแล้ว การบันทึกครั้งนี้จะเปลี่ยนผลการตรวจสอบเดิม
          </p>
        )}

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-sm font-medium">ผลการตรวจสอบ *</legend>
            {DISPOSITION_OPTIONS.map((option) => (
              <label
                key={option}
                className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 text-sm ${
                  disposition === option ? "border-status-borrowed bg-status-borrowed/10" : "border-[var(--border)]"
                }`}
              >
                <input
                  type="radio"
                  name="reconciliation-disposition"
                  value={option}
                  checked={disposition === option}
                  onChange={() => setDisposition(option)}
                  disabled={submitting}
                  className="mt-0.5 h-5 w-5 shrink-0"
                />
                <span>{RECONCILIATION_DISPOSITION_LABELS[option]}</span>
              </label>
            ))}
          </fieldset>

          <div>
            <label htmlFor="reconciliation-disposition-note" className="mb-1 block text-sm font-medium">
              หมายเหตุ (ถ้ามี)
            </label>
            <textarea
              id="reconciliation-disposition-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              disabled={submitting}
              rows={3}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
            />
            <p className={`mt-1 text-xs ${noteTooLong ? "font-medium text-status-repair" : "text-[var(--text-muted)]"}`}>
              {trimmedNote.length}/{NOTE_MAX_LENGTH} ตัวอักษร
              {noteTooLong ? " — เกินจำนวนที่กำหนด กรุณาแก้ไขให้สั้นลง" : ""}
            </p>
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
              {submitting ? "กำลังบันทึก..." : "ยืนยันผลการตรวจสอบรายการนี้"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
