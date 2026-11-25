import { CRYO_ITEMS, CUFF_TYPES, STANDARD_ITEMS } from "@/services/checks";
import type { Checks, CryoCuffChecks, Cuffs, CuffType } from "@/types";

interface ChecksEditorProps {
  checks: Checks;
  onChange: (next: Checks) => void;
  /** Receipt mode: cuff counts are "returned" counts, capped at the issued counts. */
  issuedCuffs?: Cuffs | null;
}

const countCls = "min-h-11 w-16 rounded border border-[var(--border)] bg-transparent px-2 py-1 text-center text-sm disabled:opacity-40";

function OkToggle({ label, ok, onChange }: { label: string; ok: boolean; onChange: (v: boolean) => void }) {
  return (
    <span className="inline-flex shrink-0 overflow-hidden rounded-md border border-[var(--border)]">
      <button
        type="button"
        aria-label={`${label} ปกติ`}
        aria-pressed={ok}
        onClick={() => onChange(true)}
        className={`min-h-11 min-w-11 px-3 py-1 text-sm ${ok ? "bg-status-available/20 text-status-available" : ""}`}
      >
        ✓
      </button>
      <button
        type="button"
        aria-label={`${label} ไม่ปกติ`}
        aria-pressed={!ok}
        onClick={() => onChange(false)}
        className={`min-h-11 min-w-11 px-3 py-1 text-sm ${!ok ? "bg-orange-500/20 text-orange-400" : ""}`}
      >
        ✗
      </button>
    </span>
  );
}

// Roadmap PR28 (D4/D10): the 3-item accessory checklist (checkboxes, default
// checked) or the 6-item Cryo-Cuff form (per-item ✓/✗ toggles, default ✓, plus
// the four cuff types with counts).
export function ChecksEditor({ checks, onChange, issuedCuffs }: ChecksEditorProps) {
  if (checks.kind === "standard") {
    return (
      <div className="flex flex-col gap-1.5">
        {STANDARD_ITEMS.map((it) => (
          <label key={it.key} className="flex min-h-11 items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={checks[it.key]}
              onChange={(e) => onChange({ ...checks, [it.key]: e.target.checked })}
            />
            {it.label}
          </label>
        ))}
      </div>
    );
  }

  const cryo: CryoCuffChecks = checks;
  const setCuff = (t: CuffType, n: number) => {
    const max = issuedCuffs ? issuedCuffs[t] : 99;
    const v = Math.max(0, Math.min(max, Number.isFinite(n) ? Math.trunc(n) : 0));
    onChange({ ...cryo, cuffs: { ...cryo.cuffs, [t]: v } });
  };

  return (
    <ol className="flex flex-col gap-2">
      {CRYO_ITEMS.map((it) => (
        <li key={it.key} className="flex flex-col gap-1">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm">
              {it.no} {it.label}
              {it.hint && <span className="block text-xs text-[var(--text-muted)]">({it.hint})</span>}
            </span>
            <OkToggle
              label={`${it.no} ${it.label}`}
              ok={cryo[it.key]}
              onChange={(v) => onChange({ ...cryo, [it.key]: v })}
            />
          </div>
          {it.key === "cuff_ok" && (
            <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 pl-4">
              {CUFF_TYPES.map((c) => {
                const n = cryo.cuffs[c.key];
                const max = issuedCuffs ? issuedCuffs[c.key] : 99;
                const unavailable = max === 0;
                return (
                  <div key={c.key} className="flex min-h-11 items-center gap-2 text-sm">
                    <label className="flex min-h-11 min-w-0 flex-1 items-center gap-2">
                    <input
                      type="checkbox"
                      aria-label={c.label}
                      checked={n > 0}
                      disabled={unavailable}
                      onChange={(e) => setCuff(c.key, e.target.checked ? Math.max(1, n || (issuedCuffs ? max : 1)) : 0)}
                    />
                    <span className="min-w-0 flex-1">{c.label}</span>
                    </label>
                    <input
                      type="number"
                      min={0}
                      max={max}
                      aria-label={`จำนวน ${c.label}`}
                      value={n}
                      disabled={unavailable}
                      onChange={(e) => setCuff(c.key, Number(e.target.value))}
                      className={countCls}
                    />
                  </div>
                );
              })}
            </div>
          )}
        </li>
      ))}
    </ol>
  );
}
