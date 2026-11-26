import { useState } from "react";

import { HN_MAX_LENGTH, sanitizeHn } from "@/components/entry/HnField";
import { apiErrorCode } from "@/services/api";
import { addHn } from "@/services/borrow";

// Roadmap PR34 (Owner Governance 2026-11-26 D15): add an HN to an OPEN dispatch
// that has none (Standby becomes "in use"). Online only (no offline queue).
// The HN is typed into a masked input, lives in component state only, and is
// cleared as soon as the request settles; nothing here logs or persists it.

const ERROR_MESSAGES: Record<string, string> = {
  HN_ALREADY_RECORDED: "รายการนี้มี HN แล้ว ไม่สามารถแทนที่ได้",
  TRANSACTION_NOT_OPEN: "รายการนี้ปิดแล้ว ไม่สามารถเพิ่ม HN ได้",
  HN_UNAVAILABLE: "HN ใช้งานไม่ได้ (ไม่พบกุญแจเข้ารหัส)",
};

interface Props {
  transactionId: string;
  /** Called after the HN was saved so the caller can refresh its list. */
  onAdded?: () => void;
}

export function AddHnAction({ transactionId, onAdded }: Props) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    setOpen(false);
    setValue("");
    setError(null);
  };

  const save = async () => {
    if (!value) return;
    setBusy(true);
    setError(null);
    try {
      await addHn(transactionId, value);
      close();
      onAdded?.();
    } catch (e) {
      const code = apiErrorCode(e);
      setError((code && ERROR_MESSAGES[code]) || "เพิ่ม HN ไม่สำเร็จ กรุณาตรวจสอบรูปแบบและลองใหม่");
      setValue("");
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded-md border border-[var(--border)] px-2 py-1 text-xs"
      >
        เพิ่ม HN
      </button>
    );
  }

  return (
    <span className="inline-flex flex-wrap items-center gap-2" role="group" aria-label="เพิ่ม HN">
      <input
        type="password"
        aria-label="HN ผู้ป่วย"
        autoComplete="off"
        spellCheck={false}
        maxLength={HN_MAX_LENGTH}
        value={value}
        onChange={(e) => setValue(sanitizeHn(e.target.value))}
        className="w-36 rounded-md border border-[var(--border)] bg-transparent px-2 py-1 text-sm"
      />
      <button
        type="button"
        onClick={() => void save()}
        disabled={busy || value === ""}
        className="rounded-md border border-[var(--border)] px-2 py-1 text-xs disabled:opacity-60"
      >
        บันทึก HN
      </button>
      <button type="button" onClick={close} disabled={busy} className="rounded-md px-2 py-1 text-xs">
        ยกเลิก
      </button>
      {error && (
        <span role="alert" className="text-xs text-status-repair">
          {error}
        </span>
      )}
    </span>
  );
}
