import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { resolveBcmText } from "@/components/entry/lookup";
import { ScanBar } from "@/components/entry/ScanBar";
import { canCorrectTransactionWard, useAuth } from "@/hooks/useAuth";
import { apiErrorMessage } from "@/services/api";
import {
  WARD_CORRECTION_REASON_MAX_LENGTH,
  changeTransactionDevice,
  switchTransactionAction,
  voidTransaction,
} from "@/services/borrow";
import { getEquipment, resolveEquipmentByQr } from "@/services/equipment";
import { listWards } from "@/services/masterData";
import type { ReceiptOutcome, TransactionOut } from "@/types";

// Owner Governance 2026-11-27 (D28, layer 3): audited corrections of a
// device's LATEST non-voided transaction. The caller decides "latest"; the
// permission check here is usability only (administrator always, pool staff
// for their own entry in the same shift) -- the backend enforces it and its
// 403 / 409 message is shown as-is. The transaction carries no operator id,
// so the menu is offered to every pool operator and the server arbitrates.

type Mode = "void" | "change" | "switch";

export function isDispatchEvent(tx: TransactionOut): boolean {
  return tx.status === "open";
}

/** A closed row without a receipt was closed by re-dispatch and is never correctable. */
export function isCorrectableShape(tx: TransactionOut): boolean {
  return tx.status === "open" || (tx.status === "closed" && !!tx.returned_at);
}

interface Props {
  transaction: TransactionOut;
  onCorrected: (message: string) => void;
}

export function TransactionCorrectionMenu({ transaction, onCorrected }: Props) {
  const { user } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [mode, setMode] = useState<Mode | null>(null);

  if (!canCorrectTransactionWard(user) || !isCorrectableShape(transaction)) return null;

  const pick = (m: Mode) => {
    setMenuOpen(false);
    setMode(m);
  };

  return (
    <div className="relative inline-block">
      <button
        type="button"
        aria-expanded={menuOpen}
        onClick={() => setMenuOpen((o) => !o)}
        className="min-h-11 rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
      >
        แก้ไขรายการ
      </button>
      {menuOpen && (
        <ul role="menu" className="surface absolute left-0 z-20 mt-1 flex w-44 flex-col rounded-lg border p-1 shadow-lg">
          {(
            [
              ["void", "ยกเลิกรายการ"],
              ["change", "เปลี่ยนเครื่อง"],
              ["switch", "สลับงาน"],
            ] as const
          ).map(([m, label]) => (
            <li key={m} role="none">
              <button type="button" role="menuitem" onClick={() => pick(m)} className="min-h-11 w-full rounded-md px-3 text-left text-sm">
                {label}
              </button>
            </li>
          ))}
        </ul>
      )}
      {mode && (
        <CorrectionDialog
          mode={mode}
          transaction={transaction}
          onClose={() => setMode(null)}
          onDone={(msg) => {
            setMode(null);
            onCorrected(msg);
          }}
        />
      )}
    </div>
  );
}

const TITLES: Record<Mode, string> = { void: "ยกเลิกรายการ", change: "เปลี่ยนเครื่อง", switch: "สลับงาน" };
const DONE: Record<Mode, string> = { void: "ยกเลิกรายการแล้ว", change: "เปลี่ยนเครื่องแล้ว", switch: "สลับงานแล้ว" };

function CorrectionDialog({
  mode,
  transaction,
  onClose,
  onDone,
}: {
  mode: Mode;
  transaction: TransactionOut;
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const dispatch = isDispatchEvent(transaction);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [target, setTarget] = useState<{ id: string; label: string } | null>(null);
  const [outcome, setOutcome] = useState<ReceiptOutcome>("usable");
  const [wardId, setWardId] = useState("");
  const needWards = mode === "switch" && !dispatch;
  const { data: wards } = useQuery({ queryKey: ["wards"], queryFn: listWards, enabled: needWards });

  const trimmed = reason.trim();
  const tooLong = trimmed.length > WARD_CORRECTION_REASON_MAX_LENGTH;
  const ready =
    trimmed.length > 0 && !tooLong && (mode !== "change" || !!target) && (!needWards || !!wardId) && !busy;

  const labelOf = (e: { bcm_code?: string | null; asset_number?: string | null; equipment_name: string }) =>
    e.bcm_code ?? e.asset_number ?? e.equipment_name;

  const pickByBcm = async (text: string) => {
    setError(null);
    try {
      const s = await resolveBcmText(text, false);
      if (!s) return setError(`ไม่พบเครื่อง ${text}`);
      setTarget({ id: s.id, label: labelOf(await getEquipment(s.id)) });
    } catch (err) {
      setError(apiErrorMessage(err, `ไม่พบเครื่อง ${text}`));
    }
  };
  const pickByQr = async (raw: string) => {
    setError(null);
    try {
      const eq = await resolveEquipmentByQr(raw);
      setTarget({ id: eq.id, label: labelOf(eq) });
    } catch (err) {
      setError(apiErrorMessage(err, "ไม่พบเครื่องมือจาก QR ที่สแกน"));
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "void") await voidTransaction(transaction.id, trimmed);
      else if (mode === "change") await changeTransactionDevice(transaction.id, { reason: trimmed, equipment_id: target!.id });
      else
        await switchTransactionAction(
          transaction.id,
          dispatch ? { reason: trimmed, outcome } : { reason: trimmed, ward_id: wardId },
        );
      onDone(DONE[mode]);
    } catch (err) {
      setError(apiErrorMessage(err, "แก้ไขรายการไม่สำเร็จ"));
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-4 sm:items-center" onClick={() => !busy && onClose()}>
      <form
        role="dialog"
        aria-modal="true"
        aria-label={TITLES[mode]}
        onClick={(e) => e.stopPropagation()}
        onSubmit={submit}
        className="surface flex w-full max-w-sm flex-col gap-3 rounded-xl border p-4"
      >
        <h2 className="text-base font-semibold">{TITLES[mode]}</h2>
        <p className="text-sm text-[var(--text-muted)]">
          {transaction.transaction_no} · {dispatch ? "เบิก" : "รับคืน"}
        </p>

        {mode === "change" && (
          <div className="flex flex-col gap-2">
            <p className="text-sm font-medium">เครื่องที่ถูกต้อง *</p>
            <ScanBar onBcm={(t) => void pickByBcm(t)} onQr={(r) => void pickByQr(r)} />
            {target && <p className="text-sm">เปลี่ยนเป็น <strong>{target.label}</strong></p>}
          </div>
        )}

        {mode === "switch" && dispatch && (
          <div>
            <p className="mb-1 text-sm font-medium">เปลี่ยนเป็นรับคืน — ผลการรับคืน</p>
            <div className="grid grid-cols-2 gap-2">
              {(
                [
                  ["usable", "ใช้งานได้"],
                  ["defective", "เสีย"],
                ] as const
              ).map(([v, label]) => (
                <button
                  key={v}
                  type="button"
                  aria-pressed={outcome === v}
                  onClick={() => setOutcome(v)}
                  className={`min-h-11 rounded-lg border px-3 text-sm ${outcome === v ? "border-status-borrowed bg-status-borrowed/10" : "border-[var(--border)]"}`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        )}

        {needWards && (
          <div>
            <label htmlFor="correction-ward" className="mb-1 block text-sm font-medium">
              เปลี่ยนเป็นเบิก — หอผู้ป่วย *
            </label>
            <select
              id="correction-ward"
              value={wardId}
              onChange={(e) => setWardId(e.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-3 text-base"
            >
              <option value="">- เลือกหอผู้ป่วย -</option>
              {(wards ?? []).map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </div>
        )}

        <div>
          <label htmlFor="correction-reason" className="mb-1 block text-sm font-medium">
            เหตุผล *
          </label>
          <textarea
            id="correction-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
          />
          {tooLong && <p className="text-xs text-status-repair">เกิน {WARD_CORRECTION_REASON_MAX_LENGTH} ตัวอักษร</p>}
        </div>

        {error && (
          <p role="alert" className="text-sm text-status-repair">
            {error}
          </p>
        )}

        <div className="flex gap-2">
          <button type="button" onClick={onClose} disabled={busy} className="min-h-11 flex-1 rounded-lg border border-[var(--border)] font-medium disabled:opacity-60">
            ปิด
          </button>
          <button type="submit" disabled={!ready} className="min-h-11 flex-1 rounded-lg bg-status-borrowed font-medium text-white disabled:opacity-60">
            {busy ? "กำลังบันทึก..." : "ยืนยัน"}
          </button>
        </div>
      </form>
    </div>
  );
}
