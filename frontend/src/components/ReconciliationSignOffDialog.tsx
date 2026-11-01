import { useEffect, useRef, useState } from "react";

import { apiErrorCode, apiErrorMessage } from "@/services/api";
import { createReconciliationSignoff } from "@/services/reconciliation";
import type { ReconciliationRunDetail, ReconciliationSignOffErrorCode } from "@/types/reconciliation";

interface ReconciliationSignOffDialogProps {
  run: ReconciliationRunDetail;
  onClose: () => void;
  // Called on a successful sign-off AND on a conflict that means the run
  // is already signed off elsewhere (RECONCILIATION_SIGNOFF_ALREADY_EXISTS)
  // -- either way the caller must refetch run/sign-off state, mirroring
  // WardCorrectionDialog's onUpdated contract.
  onSettled: (message: string) => void;
  triggerRef?: React.RefObject<HTMLElement | null>;
}

// Roadmap PR22E's exact public codes for this endpoint
// (docs/api/ERROR_CODES.md) -- RECONCILIATION_SIGNOFF_ALREADY_EXISTS is
// handled separately in handleConfirm (it means "refetch and show the
// existing attestation", not just "show this message").
const SIGNOFF_ERROR_MESSAGES: Partial<Record<ReconciliationSignOffErrorCode, string>> = {
  RECONCILIATION_RUN_NOT_FOUND: "ไม่พบรอบการตรวจสอบนี้แล้ว อาจมีการเปลี่ยนแปลงไปก่อนหน้านี้",
  RECONCILIATION_SIGNOFF_RUN_NOT_COMPLETED: "รอบการตรวจสอบนี้ยังไม่เสร็จสิ้นการประมวลผล จึงยังไม่สามารถลงนามยืนยันได้",
  RECONCILIATION_SIGNOFF_FINDINGS_INCOMPLETE: "ยังมีรายการที่ยังไม่ได้ตรวจสอบในรอบนี้ กรุณาตรวจสอบให้ครบก่อนลงนามยืนยัน",
  RECONCILIATION_SIGNOFF_REQUIRES_CORRECTION:
    "มีรายการที่ถูกระบุว่า “ต้องดำเนินการแก้ไข” อยู่ในรอบนี้ จึงยังไม่สามารถลงนามยืนยันได้จนกว่าจะดำเนินการแก้ไข",
  // Fail closed -- never attempt to compute or repair counts on the
  // frontend for either of these two (§28 of the task).
  RECONCILIATION_SIGNOFF_EVIDENCE_INCONSISTENT:
    "ระบบตรวจพบความไม่สอดคล้องของข้อมูลหลักฐานในรอบนี้ กรุณาแจ้งผู้ดูแลระบบเพื่อตรวจสอบก่อนดำเนินการต่อ",
  RECONCILIATION_COVERAGE_MISMATCH:
    "ข้อมูลช่วงเวลาที่ได้รับอนุมัติของรอบนี้ไม่ตรงกับข้อมูลปัจจุบัน กรุณาหยุดดำเนินการและแจ้งผู้ดูแลระบบเพื่อตรวจสอบ",
};

const VERSION_CONFLICT_MESSAGE =
  "ข้อมูลรอบการตรวจสอบนี้ถูกเปลี่ยนแปลงไปก่อนหน้านี้ ระบบได้โหลดข้อมูลล่าสุดให้แล้ว กรุณาตรวจสอบแล้วลองอีกครั้งหากต้องการ";

function getFocusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )
  );
}

// Roadmap PR22F §27/§29 of the task -- a strong, explicit confirmation
// dialog because sign-off is irreversible, mirroring
// WardCorrectionDialog's established focus-trap/keyboard pattern
// exactly. This component NEVER decides whether sign-off is eligible: it
// submits `{ expected_version: run.version }` and lets the POST
// response (success or one of the structured errors above) be the only
// authority, per the task's own §29 "No client-side sign-off eligibility
// engine" rule.
export function ReconciliationSignOffDialog({ run, onClose, onSettled, triggerRef }: ReconciliationSignOffDialogProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  const handleConfirm = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await createReconciliationSignoff(run.id, { expected_version: run.version });
      onSettled("ลงนามยืนยันผลการตรวจสอบสำเร็จ");
      return;
    } catch (err) {
      const code = apiErrorCode(err) as ReconciliationSignOffErrorCode | undefined;
      if (code === "RECONCILIATION_SIGNOFF_ALREADY_EXISTS") {
        onSettled("รอบการตรวจสอบนี้ถูกลงนามยืนยันไปแล้วโดยผู้ใช้อื่น ระบบได้แสดงข้อมูลล่าสุดให้แล้ว");
        return;
      }
      if (code === "RECONCILIATION_SIGNOFF_VERSION_CONFLICT") {
        setError(VERSION_CONFLICT_MESSAGE);
        setSubmitting(false);
        return;
      }
      const knownMessage = code ? SIGNOFF_ERROR_MESSAGES[code] : undefined;
      setError(knownMessage ?? apiErrorMessage(err, "ลงนามยืนยันไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"));
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
        aria-labelledby="reconciliation-signoff-title"
        aria-describedby="reconciliation-signoff-warning"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className="surface flex w-full max-w-sm flex-col gap-3 rounded-xl border p-4 outline-none"
      >
        <h2 id="reconciliation-signoff-title" className="text-base font-semibold">
          ยืนยันการลงนามผลการตรวจสอบ
        </h2>

        <div id="reconciliation-signoff-warning" className="rounded-lg border border-[var(--border)] bg-[var(--border)]/10 p-3 text-sm">
          การลงนามจะยืนยันผลการตรวจสอบของรอบนี้และไม่สามารถแก้ไขผลการตรวจสอบภายหลังได้ ต้องการดำเนินการต่อหรือไม่
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
            type="button"
            onClick={handleConfirm}
            disabled={submitting}
            className="flex-1 rounded-lg bg-status-borrowed py-2.5 font-medium text-white disabled:opacity-60"
          >
            {submitting ? "กำลังบันทึก..." : "ยืนยันและลงนาม"}
          </button>
        </div>
      </div>
    </div>
  );
}
