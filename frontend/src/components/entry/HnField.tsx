import { useCallback, useEffect, useRef, useState } from "react";

import { apiErrorCode } from "@/services/api";
import { revealHn } from "@/services/borrow";

// Roadmap PR29 (Owner Governance 2026-11-25 D1): patient HN UI.
// * An HN is never shown by default: after entry it is masked (●●●) and only an
//   explicit "แสดง HN" click shows it, for REVEAL_SECONDS, then it hides again.
// * Values live in component state only: never in localStorage, URLs, logs or
//   query keys. Nothing in this file calls console.*.

export const REVEAL_SECONDS = 30;
export const HN_MAX_LENGTH = 20;
const HN_ALLOWED = /[^A-Za-z0-9/-]/g;
const MASK = "●●●";

/** Strip anything the server would reject (letters, digits, '-', '/' only). */
export function sanitizeHn(raw: string): string {
  return raw.replace(HN_ALLOWED, "").slice(0, HN_MAX_LENGTH);
}

/** A value that is visible only for `seconds` after `show`, then hides itself. */
export function useTimedReveal(seconds = REVEAL_SECONDS) {
  const [visible, setVisible] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clear = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };
  const hide = useCallback(() => {
    clear();
    setVisible(false);
  }, []);
  const show = useCallback(() => {
    clear();
    setVisible(true);
    timer.current = setTimeout(() => setVisible(false), seconds * 1000);
  }, [seconds]);
  useEffect(() => clear, []);
  return { visible, show, hide };
}

/** "🔒HN" marker for a row; nothing when no HN was entered. */
export function HnIndicator({ hn }: { hn: string }) {
  if (!hn.trim()) return null;
  return (
    <span aria-label="มี HN" className="whitespace-nowrap text-xs">
      🔒HN
    </span>
  );
}

interface HnFieldProps {
  value: string;
  onChange: (hn: string) => void;
}

const inputCls = "min-h-11 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm";
const btnCls = "min-h-11 shrink-0 whitespace-nowrap rounded-md border border-[var(--border)] px-3 text-[13px]";

/**
 * Optional HN input for one equipment on the dispatch screen. Empty = no HN.
 * Once a value is entered (field left) it is masked; "แสดง HN" shows the local
 * value for 30 s.
 */
export function HnField({ value, onChange }: HnFieldProps) {
  const [editing, setEditing] = useState(value === "");
  const reveal = useTimedReveal();

  useEffect(() => {
    if (value === "") setEditing(true);
  }, [value]);

  if (editing || value === "") {
    return (
      <div className="flex flex-col gap-1">
        <label className="text-xs text-[var(--text-muted)]" htmlFor="hn-input">
          HN ผู้ป่วย (ไม่บังคับ)
        </label>
        <input
          id="hn-input"
          aria-label="HN ผู้ป่วย (ไม่บังคับ)"
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          inputMode="text"
          maxLength={HN_MAX_LENGTH}
          value={value}
          onChange={(e) => onChange(sanitizeHn(e.target.value))}
          onBlur={() => {
            if (value !== "") setEditing(false);
          }}
          placeholder="เช่น 123456"
          className={inputCls}
        />
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 text-sm" role="group" aria-label="HN ผู้ป่วย">
      <span className="text-xs text-[var(--text-muted)]">🔒HN</span>
      {reveal.visible ? (
        <strong data-testid="hn-value">{value}</strong>
      ) : (
        <span aria-label="HN ถูกซ่อน" data-testid="hn-masked">
          {MASK}
        </span>
      )}
      <span className="flex-1" />
      {reveal.visible ? (
        <button type="button" onClick={reveal.hide} className={btnCls}>
          ซ่อน HN
        </button>
      ) : (
        <button type="button" onClick={reveal.show} className={btnCls}>
          แสดง HN
        </button>
      )}
      <button
        type="button"
        onClick={() => {
          reveal.hide();
          setEditing(true);
        }}
        className={btnCls}
      >
        แก้ไข HN
      </button>
    </div>
  );
}

interface HnRevealProps {
  transactionId: string;
  /** Smaller inline rendering for list rows. */
  compact?: boolean;
}

/**
 * HN of an existing transaction: 🔒HN with a "แสดง HN" button. Clicking calls
 * POST /transactions/{id}/reveal-hn (audited server-side), shows the value for
 * 30 s, then hides it and drops it from memory.
 */
export function HnReveal({ transactionId, compact = false }: HnRevealProps) {
  const [value, setValue] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const drop = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    setValue(null);
  }, []);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const click = async () => {
    setBusy(true);
    setError(null);
    try {
      const hn = await revealHn(transactionId);
      setValue(hn);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setValue(null), REVEAL_SECONDS * 1000);
    } catch (e) {
      setValue(null);
      setError(
        apiErrorCode(e) === "HN_UNAVAILABLE"
          ? "HN ใช้งานไม่ได้ (ไม่พบกุญแจเข้ารหัส)"
          : "แสดง HN ไม่สำเร็จ",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className={`inline-flex flex-wrap items-center gap-2 ${compact ? "text-xs" : "text-sm"}`}>
      <span>🔒HN</span>
      {value !== null ? (
        <>
          <strong data-testid="hn-value">{value}</strong>
          <button type="button" onClick={drop} className="rounded-md border border-[var(--border)] px-2 py-1 text-xs">
            ซ่อน HN
          </button>
        </>
      ) : (
        <>
          <span aria-label="HN ถูกซ่อน" data-testid="hn-masked">
            {MASK}
          </span>
          <button
            type="button"
            onClick={() => void click()}
            disabled={busy}
            className="rounded-md border border-[var(--border)] px-2 py-1 text-xs disabled:opacity-60"
          >
            แสดง HN
          </button>
        </>
      )}
      {error && (
        <span role="alert" className="text-xs text-status-repair">
          {error}
        </span>
      )}
    </span>
  );
}
