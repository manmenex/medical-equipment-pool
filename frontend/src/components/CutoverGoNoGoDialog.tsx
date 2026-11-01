import { useEffect, useRef, useState } from "react";

import { apiErrorCode, apiErrorMessage } from "@/services/api";
import { createCutoverDecision } from "@/services/cutoverReadiness";
import type {
  CutoverGateEvaluationItem,
  CutoverGoNoGoDecisionValue,
  CutoverReadinessErrorCode,
  CutoverReadinessRunDetail,
} from "@/types/cutoverReadiness";

interface CutoverGoNoGoDialogProps {
  run: CutoverReadinessRunDetail;
  decision: CutoverGoNoGoDecisionValue;
  // Only meaningful for GO -- the *current* live warning items from the
  // most recent GET .../gate-evaluation response. Never a cached/earlier
  // evaluation; the parent page re-fetches gate-evaluation before opening
  // this dialog for GO so these are as fresh as the frontend can make
  // them -- the backend still re-evaluates fresh again on submit
  // regardless (§4/§22 of the task).
  liveWarningItems: CutoverGateEvaluationItem[];
  onClose: () => void;
  // Called on a successful decision AND on CUTOVER_DECISION_ALREADY_EXISTS
  // (means someone else recorded a decision first) -- either way the
  // caller must close this dialog and refetch decision/run/gate state,
  // mirroring ReconciliationSignOffDialog's onSettled contract.
  onResolved: (message: string) => void;
  // Called on a structured error that means the frontend's snapshot of
  // run/gate-evaluation state is stale (version conflict, superseded run,
  // a blocker or unacknowledged warning that changed since this dialog
  // opened) -- the dialog stays open so the operator can see the error,
  // but the caller must refetch run/gate-evaluation state in the
  // background so a retry (if the operator chooses to) uses fresh data.
  onStaleDataDetected: () => void;
  triggerRef?: React.RefObject<HTMLElement | null>;
}

const NO_GO_REASON_MAX_LENGTH = 2000;

// This dialog's own public codes (docs/api/ERROR_CODES.md, PR23D) --
// ALREADY_EXISTS is handled separately (means "refetch and show the
// existing decision", not just a message).
const DECISION_ERROR_MESSAGES: Partial<Record<CutoverReadinessErrorCode, string>> = {
  CUTOVER_READINESS_RUN_NOT_FOUND: "ไม่พบรอบความพร้อมนี้แล้ว อาจมีการเปลี่ยนแปลงไปก่อนหน้านี้",
  CUTOVER_DECISION_REQUIRES_COMPLETED_RUN: "รอบความพร้อมนี้ยังไม่มีการบันทึกหลักฐานครบถ้วน จึงยังไม่สามารถบันทึกผล GO/NO-GO ได้",
  CUTOVER_DECISION_RUN_SUPERSEDED: "รอบความพร้อมนี้ถูกแทนที่ด้วยรอบใหม่แล้ว ระบบได้โหลดข้อมูลล่าสุดให้แล้ว",
  CUTOVER_DECISION_BLOCKED_BY_READINESS: "ไม่สามารถบันทึก GO ได้ เนื่องจากยังมีรายการที่เป็นตัวบล็อก ระบบได้โหลดผลตรวจสอบล่าสุดให้แล้ว",
  CUTOVER_DECISION_WARNINGS_NOT_ACKNOWLEDGED: "กรุณารับทราบคำเตือนปัจจุบันให้ครบก่อนยืนยัน GO ระบบได้โหลดรายการล่าสุดให้แล้ว",
};

const STALE_VERSION_MESSAGE =
  "ข้อมูลรอบความพร้อมนี้เปลี่ยนแปลงไปก่อนหน้านี้ ระบบได้โหลดข้อมูลล่าสุดให้แล้ว กรุณาตรวจสอบแล้วลองอีกครั้งหากต้องการ";

// Structured codes that mean "the frontend's snapshot is stale, refetch
// but keep this dialog open" -- distinct from ALREADY_EXISTS (terminal,
// handled separately below).
const STALE_DATA_CODES: ReadonlySet<CutoverReadinessErrorCode> = new Set([
  "CUTOVER_DECISION_STALE_VERSION",
  "CUTOVER_DECISION_RUN_SUPERSEDED",
  "CUTOVER_DECISION_BLOCKED_BY_READINESS",
  "CUTOVER_DECISION_WARNINGS_NOT_ACKNOWLEDGED",
]);

function getFocusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )
  );
}

// Roadmap PR23E §21-26 of the task -- a strong, explicit confirmation
// dialog because a Go/No-Go decision is immutable, mirroring
// ReconciliationSignOffDialog's established focus-trap/keyboard pattern
// exactly. This component NEVER decides whether GO is eligible: it
// submits exactly { expected_version, decision, acknowledged_warning_codes,
// no_go_reason } and lets the POST response (success or one of the
// structured errors above) be the only authority (§4 of the task -- "the
// frontend must never calculate authoritative readiness"). Warning
// acknowledgement codes are drawn exclusively from `liveWarningItems`,
// the current gate-evaluation response -- the operator can never type an
// arbitrary code (§6/§23 of the task).
export function CutoverGoNoGoDialog({
  run,
  decision,
  liveWarningItems,
  onClose,
  onResolved,
  onStaleDataDetected,
  triggerRef,
}: CutoverGoNoGoDialogProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [acknowledged, setAcknowledged] = useState<Set<string>>(new Set());
  const [noGoReason, setNoGoReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isGo = decision === "GO";

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

  function toggleAcknowledged(code: string) {
    setAcknowledged((prev) => {
      const next = new Set(prev);
      if (next.has(code)) {
        next.delete(code);
      } else {
        next.add(code);
      }
      return next;
    });
  }

  const trimmedReason = noGoReason.trim();
  const reasonTooLong = trimmedReason.length > NO_GO_REASON_MAX_LENGTH;
  // Deliberate-acknowledgement UX guidance only (§23 of the task) -- every
  // live warning code must be checked before GO is offered as submittable.
  // This is NOT the authorization boundary: the backend independently
  // re-checks acknowledgement against a fresh evaluation on submit
  // regardless of what this frontend gate allows through.
  const allWarningsAcknowledged = liveWarningItems.every((item) => acknowledged.has(item.code));
  const canSubmit = isGo ? allWarningsAcknowledged && !submitting : !reasonTooLong && !submitting;

  const handleConfirm = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      await createCutoverDecision(run.id, {
        expected_version: run.version,
        decision,
        acknowledged_warning_codes: isGo ? Array.from(acknowledged) : [],
        no_go_reason: isGo ? undefined : trimmedReason || null,
      });
      onResolved(isGo ? "บันทึกผลอนุมัติ GO สำเร็จ" : "บันทึกผลไม่อนุมัติ NO-GO สำเร็จ");
      return;
    } catch (err) {
      const code = apiErrorCode(err) as CutoverReadinessErrorCode | undefined;
      if (code === "CUTOVER_DECISION_ALREADY_EXISTS") {
        onResolved("รอบนี้มีการบันทึกผล GO/NO-GO แล้วโดยผู้ใช้อื่น ระบบได้แสดงข้อมูลล่าสุดให้แล้ว");
        return;
      }
      if (code === "CUTOVER_DECISION_STALE_VERSION") {
        setError(STALE_VERSION_MESSAGE);
        onStaleDataDetected();
        setSubmitting(false);
        return;
      }
      if (code && STALE_DATA_CODES.has(code)) {
        setError(DECISION_ERROR_MESSAGES[code] ?? apiErrorMessage(err));
        onStaleDataDetected();
        setSubmitting(false);
        return;
      }
      const knownMessage = code ? DECISION_ERROR_MESSAGES[code] : undefined;
      setError(knownMessage ?? apiErrorMessage(err, "บันทึกผลไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"));
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
        aria-labelledby="cutover-decision-title"
        aria-describedby="cutover-decision-warning"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className="surface flex max-h-[85vh] w-full max-w-md flex-col gap-3 overflow-y-auto rounded-xl border p-4 outline-none"
      >
        <h2 id="cutover-decision-title" className="text-base font-semibold">
          {isGo ? "ยืนยันอนุมัติเปลี่ยนระบบ (GO)" : "ยืนยันไม่อนุมัติเปลี่ยนระบบ (NO-GO)"}
        </h2>

        <div
          id="cutover-decision-warning"
          className="rounded-lg border border-[var(--border)] bg-[var(--border)]/10 p-3 text-sm"
        >
          การบันทึกผล {isGo ? "GO" : "NO-GO"} จะยืนยันผลตัดสินใจของรอบความพร้อมนี้และไม่สามารถแก้ไขภายหลังได้
          {isGo && " ระบบจะตรวจสอบความพร้อมอีกครั้งเมื่อยืนยัน"}
        </div>

        {isGo && liveWarningItems.length > 0 && (
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-sm font-medium">รับทราบคำเตือนก่อนยืนยัน *</legend>
            {liveWarningItems.map((item) => (
              <label
                key={item.code}
                className="flex cursor-pointer items-start gap-3 rounded-lg border border-[var(--border)] p-3 text-sm"
              >
                <input
                  type="checkbox"
                  checked={acknowledged.has(item.code)}
                  onChange={() => toggleAcknowledged(item.code)}
                  disabled={submitting}
                  className="mt-0.5 h-5 w-5 shrink-0"
                />
                <span>
                  <span className="block">{item.message}</span>
                  {item.manual_attestation_required && (
                    <span className="mt-1 block text-xs text-[var(--text-muted)]">
                      รับทราบว่ารายการนี้ต้องยืนยันจากการปฏิบัติงานจริง และระบบไม่สามารถตรวจสอบอัตโนมัติได้
                    </span>
                  )}
                </span>
              </label>
            ))}
          </fieldset>
        )}

        {!isGo && (
          <div>
            <label htmlFor="cutover-no-go-reason" className="mb-1 block text-sm font-medium">
              เหตุผล (ถ้ามี)
            </label>
            <textarea
              id="cutover-no-go-reason"
              value={noGoReason}
              onChange={(e) => setNoGoReason(e.target.value)}
              disabled={submitting}
              rows={3}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
            />
            <p className={`mt-1 text-xs ${reasonTooLong ? "font-medium text-status-repair" : "text-[var(--text-muted)]"}`}>
              {trimmedReason.length}/{NO_GO_REASON_MAX_LENGTH} ตัวอักษร
              {reasonTooLong ? " — เกินจำนวนที่กำหนด กรุณาแก้ไขให้สั้นลง" : ""}
            </p>
          </div>
        )}

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
            disabled={!canSubmit}
            className={`flex-1 rounded-lg py-2.5 font-medium text-white disabled:opacity-60 ${
              isGo ? "bg-status-available" : "bg-status-repair"
            }`}
          >
            {submitting ? "กำลังบันทึก..." : isGo ? "ยืนยันและอนุมัติ GO" : "ยืนยันและไม่อนุมัติ NO-GO"}
          </button>
        </div>
      </div>
    </div>
  );
}
