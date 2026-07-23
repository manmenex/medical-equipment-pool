import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { BcmSearchInput } from "@/components/BcmSearchInput";
import { QRScanner } from "@/components/QRScanner";
import { apiErrorCode, apiErrorMessage } from "@/services/api";
import { createReturn, listActiveBorrows } from "@/services/borrow";
import { resolveEquipmentByQr } from "@/services/equipment";
import type { BcmSuggestion, ReceiptOutcome, TransactionOut } from "@/types";

// Roadmap PR8B (knowledge/adr/ADR-006-receipt-outcome-contract.md): the
// confirmed binary receipt outcome replaces the pre-PR8B four-option
// condition radio group entirely -- a minimum functional change to the
// option set only, per the same precedent Roadmap PR7b's dispatch-form
// changes established (not the full terminology/workflow redesign
// reserved for Roadmap PR11). Roadmap PR6 / owner-confirmed cleaning
// retirement: no "cleaning" option here either, before or after this
// change -- cleaning happens as part of collecting/receiving equipment
// (AGENTS.md), never a distinct receipt outcome.
//
// Codex review round 1 (GitHub PR #29): the label and selected-state
// styling must describe the *outcome the operator observed*, not the
// *lifecycle state the backend will apply* -- conflating the two here
// would misleadingly present a defective selection with the same green
// "available" styling used elsewhere for AVAILABLE_AT_POOL, even though
// choosing it causes UNAVAILABLE_DEFECTIVE. "ชำรุด" ("defective/damaged")
// is the outcome-oriented term, distinct from StatusBadge.tsx's
// lifecycle-state label ("ไม่พร้อมใช้งาน", "not available"). Each option's
// selected-state styling below intentionally differs for the same
// reason: usable uses the available/green treatment, defective uses the
// repair/amber treatment (StatusBadge.tsx already colors
// unavailable_defective with `status-repair`) -- this is presentational
// only, no lifecycle-state value is read, stored, or submitted here.
const RECEIPT_OUTCOMES: { value: ReceiptOutcome; label: string; selectedClass: string }[] = [
  { value: "usable", label: "พร้อมใช้งาน", selectedClass: "border-status-available bg-status-available/10" },
  { value: "defective", label: "ชำรุด", selectedClass: "border-status-repair bg-status-repair/10" },
];

// Roadmap PR8C (knowledge/adr/ADR-006-receipt-outcome-contract.md's "Not
// decided here"; backend/app/core/exceptions.py): the receipt endpoint now
// rejects a losing request with one of two distinguishable, stable
// `code`s -- a genuine duplicate submission and a genuine timing race with
// another concurrent request are different situations that call for
// different operator guidance (a duplicate needs no action; a race means
// another receipt request completed first and the operator should
// refresh, not retry). Keyed by `code`, never by parsing `detail` text --
// `detail` is a free-text, human-readable message, not a stable contract.
//
// Deliberately neutral wording: RECEIPT_RACE_LOST only proves another
// receipt request committed first at the database level -- it does not
// identify who or what sent that request. It could be a different staff
// member, the same user double-clicking, a browser/network retry, or a
// duplicate submission from the same session. Never attribute this to
// "someone else"/another person -- the backend has no such evidence
// (see app.services.borrow_service.return_equipment, which does not
// compare received_by_user_id between the two requests).
const RECEIPT_ERROR_MESSAGES: Record<string, string> = {
  TRANSACTION_ALREADY_RETURNED: "รายการนี้ถูกคืนไปแล้ว",
  RECEIPT_RACE_LOST: "มีคำขอรับเครื่องอื่นดำเนินการสำเร็จก่อน กรุณารีเฟรชเพื่อดูข้อมูลล่าสุด",
};

export function ReturnPage() {
  const [searchParams] = useSearchParams();
  const presetEquipmentId = searchParams.get("equipment_id");

  const [scanning, setScanning] = useState(!presetEquipmentId);
  const [transaction, setTransaction] = useState<TransactionOut | null>(null);
  const [outcome, setOutcome] = useState<ReceiptOutcome>("usable");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const findActiveTransaction = useCallback(async (equipmentId: string) => {
    const active = await listActiveBorrows();
    const match = active.find((tx) => tx.equipment.id === equipmentId);
    if (!match) {
      throw new Error("ไม่พบรายการยืมที่ยังไม่คืนสำหรับเครื่องนี้");
    }
    return match;
  }, []);

  // Roadmap PR5 primary workflow: scan existing QR -> extract Item No
  // (server-side) -> Equipment Master lookup -> active transaction.
  const resolveByQr = useCallback(
    async (rawValue: string) => {
      setError(null);
      try {
        const eq = await resolveEquipmentByQr(rawValue);
        const tx = await findActiveTransaction(eq.id);
        setTransaction(tx);
        setScanning(false);
      } catch (err) {
        setError(err instanceof Error ? err.message : apiErrorMessage(err, "ไม่พบรายการยืม"));
      }
    },
    [findActiveTransaction]
  );

  // Roadmap PR5 fallback workflow: BCM Code search -> select a suggestion
  // -> active transaction for that equipment.
  const handleBcmSelect = useCallback(
    async (suggestion: BcmSuggestion) => {
      setError(null);
      try {
        const tx = await findActiveTransaction(suggestion.id);
        setTransaction(tx);
        setScanning(false);
      } catch (err) {
        setError(err instanceof Error ? err.message : apiErrorMessage(err, "ไม่พบรายการยืม"));
      }
    },
    [findActiveTransaction]
  );

  useEffect(() => {
    if (presetEquipmentId) {
      findActiveTransaction(presetEquipmentId)
        .then(setTransaction)
        .catch((err) => setError(err instanceof Error ? err.message : "ไม่พบรายการยืม"));
    }
  }, [presetEquipmentId, findActiveTransaction]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!transaction) return;
    setSubmitting(true);
    setError(null);
    try {
      await createReturn(transaction.id, { receipt_outcome: outcome, notes: notes || undefined });
      setSuccess(true);
    } catch (err) {
      const code = apiErrorCode(err);
      const knownMessage = code ? RECEIPT_ERROR_MESSAGES[code] : undefined;
      setError(knownMessage ?? apiErrorMessage(err, "คืนเครื่องมือไม่สำเร็จ"));
    } finally {
      setSubmitting(false);
    }
  };

  if (success) {
    return (
      <div className="surface mx-auto mt-8 max-w-sm rounded-xl border p-6 text-center">
        <div className="mb-2 text-4xl">✅</div>
        <h2 className="text-lg font-semibold">คืนเครื่องมือสำเร็จ</h2>
        <button
          onClick={() => {
            setSuccess(false);
            setTransaction(null);
            setScanning(true);
          }}
          className="mt-4 rounded-lg bg-status-available px-4 py-2 text-sm font-medium text-white"
        >
          คืนเครื่องถัดไป
        </button>
      </div>
    );
  }

  if (!transaction) {
    return (
      <div className="mx-auto flex max-w-sm flex-col gap-4">
        <h1 className="text-lg font-semibold">คืนเครื่องมือ</h1>
        <QRScanner active={scanning} onScan={resolveByQr} />
        <p className="text-center text-sm text-[var(--text-muted)]">หรือค้นหาด้วยรหัส BCM</p>
        <BcmSearchInput onSelect={handleBcmSelect} />
        {error && <p className="text-sm text-status-repair">{error}</p>}
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="mx-auto flex max-w-sm flex-col gap-4">
      <div className="surface rounded-xl border p-4">
        <div className="font-medium">{transaction.equipment.equipment_name}</div>
        <div className="text-sm text-[var(--text-muted)]">{transaction.equipment.asset_number}</div>
        <div className="mt-1 text-sm text-[var(--text-muted)]">
          {transaction.borrower_name ? `ผู้ยืม: ${transaction.borrower_name} · ` : ""}ยืมเมื่อ{" "}
          {new Date(transaction.borrowed_at).toLocaleString("th-TH")}
        </div>
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium">สภาพเครื่องเมื่อคืน</label>
        <div className="grid grid-cols-2 gap-2">
          {RECEIPT_OUTCOMES.map((o) => (
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
        <label className="mb-1 block text-sm font-medium">หมายเหตุ</label>
        <textarea
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
        {submitting ? "กำลังบันทึก..." : "ยืนยันการคืน"}
      </button>
    </form>
  );
}
