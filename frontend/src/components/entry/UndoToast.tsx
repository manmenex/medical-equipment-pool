import { useEffect, useRef, useState } from "react";

import { apiErrorMessage } from "@/services/api";
import { undoTransaction } from "@/services/borrow";

// Owner Governance 2026-11-27 (D28, layer 2): one-tap undo after saving a
// dispatch (2:00) or receipt (0:30). The server owns the window and every
// guard, so a 409/403 message is shown as-is. Never shown for offline-queued
// saves (no server transaction exists until they sync).
// Owner-set windows (D28): measured by the server from its own save time; this
// countdown is only a hint.
export const UNDO_WINDOW_SECONDS = { dispatch: 120, receipt: 30 } as const;

export interface UndoTarget {
  ids: string[];
  /** Optional display label per id (same order), used to name failures. */
  labels?: string[];
  seconds: number;
}

interface Props extends UndoTarget {
  /** Called when the window ran out (toast hides) or after the result is dismissed. */
  onClose: () => void;
  /** Called after at least one transaction was undone. */
  onUndone?: (result: { ok: number; failedIds: string[] }) => void;
}

export function formatCountdown(total: number): string {
  const s = Math.max(0, total);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function UndoToast({ ids, labels, seconds, onClose, onUndone }: Props) {
  const [left, setLeft] = useState(seconds);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: number; errors: string[] } | null>(null);
  const endsAt = useRef(Date.now() + seconds * 1000);

  useEffect(() => {
    if (busy || result) return;
    const t = setInterval(() => {
      const remaining = Math.ceil((endsAt.current - Date.now()) / 1000);
      if (remaining <= 0) {
        clearInterval(t);
        onClose();
      } else {
        setLeft(remaining);
      }
    }, 1000);
    return () => clearInterval(t);
  }, [busy, result, onClose]);

  const undo = async () => {
    if (busy) return;
    setBusy(true);
    let ok = 0;
    const errors: string[] = [];
    const failedIds: string[] = [];
    for (const [i, id] of ids.entries()) {
      try {
        await undoTransaction(id);
        ok += 1;
      } catch (err) {
        failedIds.push(id);
        const msg = apiErrorMessage(err, "เลิกทำไม่สำเร็จ");
        errors.push(labels?.[i] ? `${labels[i]}: ${msg}` : msg);
      }
    }
    setBusy(false);
    setResult({ ok, errors });
    if (ok > 0) onUndone?.({ ok, failedIds });
  };

  const box = "surface fixed inset-x-4 bottom-4 z-40 mx-auto flex max-w-md flex-col gap-1 rounded-xl border p-3 text-sm shadow-lg";

  if (result) {
    return (
      <div role="status" className={box}>
        {result.ok > 0 && <p className="text-status-available">เลิกทำแล้ว {result.ok} รายการ</p>}
        {result.errors.map((m, i) => (
          <p key={i} role="alert" className="text-status-repair">
            ✗ {m}
          </p>
        ))}
        <button type="button" onClick={onClose} className="min-h-11 self-end rounded-lg border border-[var(--border)] px-3 text-sm">
          ปิด
        </button>
      </div>
    );
  }

  return (
    <div role="status" className={box}>
      <button
        type="button"
        onClick={() => void undo()}
        disabled={busy}
        className="min-h-11 w-full rounded-lg bg-status-borrowed/15 px-3 text-left font-medium text-status-borrowed disabled:opacity-60"
      >
        {busy ? "กำลังเลิกทำ..." : `บันทึกแล้ว · เลิกทำ (${formatCountdown(left)})`}
      </button>
    </div>
  );
}
