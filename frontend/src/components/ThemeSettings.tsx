import { useEffect, useState } from "react";

import { useSaveUserTheme, useUserTheme } from "@/hooks/useUserTheme";
import {
  DEFAULT_CUSTOM,
  FONT_LABELS,
  PRESETS,
  applyPreferences,
  contrastWarning,
  isValidHex,
  readCachedPreferences,
  type FontFamilyKey,
  type ThemeMode,
  type UiPreferences,
} from "@/lib/theme";

const MODES: [ThemeMode, string][] = [
  ["system", "ตามระบบ"],
  ["light", "สว่าง"],
  ["dark", "มืด"],
  ["custom", "กำหนดเอง"],
];
const COLOR_FIELDS = [
  ["bg", "พื้นหลัง"],
  ["surface", "การ์ด"],
  ["text", "ตัวอักษร"],
  ["accent", "สีหลัก"],
] as const;

function ColorField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="w-24">{label}</span>
      <input type="color" aria-label={`${label} (ตัวเลือกสี)`} value={value} onChange={(e) => onChange(e.target.value)} />
      <input
        aria-label={`${label} (รหัสสี)`}
        value={draft}
        maxLength={7}
        className="w-28 px-2 font-mono"
        onChange={(e) => {
          setDraft(e.target.value);
          if (isValidHex(e.target.value)) onChange(e.target.value);
        }}
      />
      {!isValidHex(draft) && <span className="text-xs text-status-repair">รูปแบบ #RRGGBB</span>}
    </div>
  );
}

export function ThemeSettings() {
  const { prefs } = useUserTheme();
  const save = useSaveUserTheme();
  const [draft, setDraft] = useState<UiPreferences>(() => readCachedPreferences() ?? {});
  const [touched, setTouched] = useState(false);
  useEffect(() => {
    // Adopt the server copy once, unless the user already started editing.
    if (prefs && !touched) setDraft(prefs);
  }, [prefs, touched]);

  const mode = draft.mode ?? "system";
  const colors = {
    bg: draft.bg ?? DEFAULT_CUSTOM.bg,
    surface: draft.surface ?? DEFAULT_CUSTOM.surface,
    text: draft.text ?? DEFAULT_CUSTOM.text,
    accent: draft.accent ?? DEFAULT_CUSTOM.accent,
  };
  const warning = mode === "custom" ? contrastWarning(colors) : null;

  // Live preview: every change is applied to the page immediately; Save persists it.
  const update = (patch: UiPreferences) => {
    const next = { ...draft, ...patch };
    setTouched(true);
    setDraft(next);
    applyPreferences(next);
  };
  const reset = () => {
    setTouched(true);
    setDraft({});
    applyPreferences({});
    save.mutate({});
  };

  return (
    <section aria-labelledby="my-theme-heading" className="surface flex flex-col gap-3 rounded-xl border p-4">
      <h2 id="my-theme-heading" className="text-sm font-medium">
        ธีมของฉัน
      </h2>
      <div className="flex flex-wrap gap-2" role="group" aria-label="โหมดธีม">
        {MODES.map(([m, label]) => (
          <button
            key={m}
            type="button"
            aria-pressed={mode === m}
            onClick={() => update({ mode: m })}
            className={`rounded-lg border px-3 py-1.5 text-sm ${
              mode === m ? "border-status-borrowed bg-status-borrowed/10" : "border-[var(--border)]"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {mode === "custom" && (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap gap-2" role="group" aria-label="ชุดสีสำเร็จรูป">
            {PRESETS.map((p) => (
              <button
                key={p.name}
                type="button"
                onClick={() => update({ bg: p.bg, surface: p.surface, text: p.text, accent: p.accent })}
                className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm"
              >
                {p.name}
              </button>
            ))}
          </div>
          {COLOR_FIELDS.map(([k, label]) => (
            <ColorField key={k} label={label} value={colors[k]} onChange={(v) => update({ [k]: v })} />
          ))}
          {warning && (
            <div role="alert" className="text-sm text-status-repair">
              {warning} (ยังบันทึกได้)
            </div>
          )}
        </div>
      )}

      <label className="flex items-center gap-2 text-sm">
        <span className="w-24">ขนาดตัวอักษร</span>
        <input
          type="range"
          min={14}
          max={22}
          step={1}
          aria-label="ขนาดตัวอักษร"
          value={draft.font_size ?? 16}
          onChange={(e) => update({ font_size: Number(e.target.value) })}
        />
        <span>{draft.font_size ?? 16}px</span>
      </label>
      <label className="flex items-center gap-2 text-sm">
        <span className="w-24">ฟอนต์</span>
        <select
          aria-label="ฟอนต์"
          value={draft.font_family ?? "default"}
          onChange={(e) => update({ font_family: e.target.value as FontFamilyKey })}
        >
          {(Object.keys(FONT_LABELS) as FontFamilyKey[]).map((f) => (
            <option key={f} value={f}>
              {FONT_LABELS[f]}
            </option>
          ))}
        </select>
      </label>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => save.mutate(draft)}
          disabled={save.isPending}
          className="rounded-lg bg-status-borrowed px-3 py-1.5 text-sm text-white"
        >
          บันทึก
        </button>
        <button type="button" onClick={reset} className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm">
          คืนค่าเริ่มต้น
        </button>
        {save.isSuccess && <span className="text-xs text-[var(--text-muted)]">บันทึกแล้ว</span>}
        {save.isError && <span className="text-xs text-status-repair">บันทึกไม่สำเร็จ</span>}
      </div>
    </section>
  );
}
