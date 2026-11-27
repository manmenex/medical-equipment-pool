// Per-account theme. Server copy lives in users.ui_preferences
// (GET/PUT /me/preferences); localStorage is only an instant-paint cache.
export type ThemeMode = "system" | "light" | "dark" | "custom";
export type FontFamilyKey = "default" | "system" | "serif";

export interface UiPreferences {
  mode?: ThemeMode | null;
  bg?: string | null;
  surface?: string | null;
  text?: string | null;
  accent?: string | null;
  font_size?: number | null;
  font_family?: FontFamilyKey | null;
}

export const HEX_RE = /^#[0-9a-fA-F]{6}$/;
export const FONT_STACKS: Record<FontFamilyKey, string> = {
  default: '-apple-system, BlinkMacSystemFont, "Noto Sans Thai", "Segoe UI", sans-serif',
  system: 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  // Trirong is used only if installed on the device (not bundled); falls back to common serifs.
  serif: 'Trirong, "TH Sarabun New", "Noto Serif Thai", Georgia, "Times New Roman", serif',
};
export const FONT_LABELS: Record<FontFamilyKey, string> = {
  default: "ค่าเริ่มต้น",
  system: "ระบบ (Sans)",
  serif: "ตัวมีหัว (Serif)",
};

export const DEFAULT_CUSTOM = { bg: "#e8edf4", surface: "#ffffff", text: "#0b1220", accent: "#1d4ed8" };
export const PRESETS: { name: string; bg: string; surface: string; text: string; accent: string }[] = [
  { name: "ครีม (Cream)", bg: "#F5EFE0", surface: "#FBF7EE", text: "#2B2B2B", accent: "#8A5A2B" },
  { name: "ฟ้าอ่อน", ...DEFAULT_CUSTOM },
  { name: "มืดนุ่ม", bg: "#1b1f27", surface: "#252b36", text: "#e8eaf0", accent: "#7cb4ff" },
];

export const CACHE_KEY = "mep-user-theme";
const VAR_NAMES = [
  "--bg", "--surface", "--field", "--text", "--text-muted", "--placeholder",
  "--border", "--divider", "--focus", "--accent-rgb",
];

type RGB = [number, number, number];

export function hexToRgb(hex: string): RGB {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function rgbToHex([r, g, b]: RGB): string {
  return "#" + [r, g, b].map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0")).join("");
}
export function luminance(hex: string): number {
  const [r, g, b] = hexToRgb(hex).map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
export function contrastRatio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}
/** Mix `a` toward `b` by t (0 = a, 1 = b). */
function mix(a: string, b: string, t: number): string {
  const x = hexToRgb(a);
  const y = hexToRgb(b);
  return rgbToHex([0, 1, 2].map((i) => x[i] + (y[i] - x[i]) * t) as RGB);
}
/** Mix `fg` toward `bg` as far as possible (up to t) while keeping `min` contrast against `bg`. */
function softened(fg: string, bg: string, t: number, min: number): string {
  for (let s = t; s > 0; s -= 0.05) {
    const c = mix(fg, bg, s);
    if (contrastRatio(c, bg) >= min) return c;
  }
  return fg;
}

export function isValidHex(v: string): boolean {
  return HEX_RE.test(v);
}

/** Warning (not blocking) when text on page/card is below WCAG AA. */
export function contrastWarning(p: { bg: string; surface: string; text: string }): string | null {
  const low = Math.min(contrastRatio(p.text, p.bg), contrastRatio(p.text, p.surface));
  return low < 4.5 ? `ความคมชัดต่ำ (${low.toFixed(1)}:1) อ่านยาก` : null;
}

export function deriveVars(c: { bg: string; surface: string; text: string; accent: string }): Record<string, string> {
  return {
    "--bg": c.bg,
    "--surface": c.surface,
    "--field": c.surface,
    "--text": c.text,
    "--text-muted": softened(c.text, c.surface, 0.3, 4.5),
    "--placeholder": softened(c.text, c.surface, 0.45, 3),
    "--border": softened(c.text, c.bg, 0.5, 3),
    "--divider": mix(c.bg, c.text, 0.12),
    "--focus": c.accent,
    "--accent-rgb": hexToRgb(c.accent).join(" "),
  };
}

export function sanitize(p: unknown): UiPreferences {
  const o = (p && typeof p === "object" ? p : {}) as Record<string, unknown>;
  const out: UiPreferences = {};
  if (["system", "light", "dark", "custom"].includes(o.mode as string)) out.mode = o.mode as ThemeMode;
  for (const k of ["bg", "surface", "text", "accent"] as const) {
    if (typeof o[k] === "string" && HEX_RE.test(o[k] as string)) out[k] = o[k] as string;
  }
  if (typeof o.font_size === "number" && o.font_size >= 14 && o.font_size <= 22) out.font_size = Math.round(o.font_size);
  if (o.font_family === "default" || o.font_family === "system" || o.font_family === "serif") out.font_family = o.font_family;
  return out;
}

/** Apply preferences to :root. `{}`/null restores the app defaults (system light/dark). */
export function applyPreferences(prefsIn: UiPreferences | null | undefined): void {
  const prefs = sanitize(prefsIn);
  const root = document.documentElement;
  for (const n of VAR_NAMES) root.style.removeProperty(n);
  const mode = prefs.mode ?? "system";
  let dark: boolean;
  if (mode === "custom") {
    const c = {
      bg: prefs.bg ?? DEFAULT_CUSTOM.bg,
      surface: prefs.surface ?? DEFAULT_CUSTOM.surface,
      text: prefs.text ?? DEFAULT_CUSTOM.text,
      accent: prefs.accent ?? DEFAULT_CUSTOM.accent,
    };
    const vars = deriveVars(c);
    for (const [k, v] of Object.entries(vars)) root.style.setProperty(k, v);
    dark = luminance(c.bg) < 0.25;
  } else {
    dark =
      mode === "dark" ||
      (mode === "system" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  }
  root.classList.toggle("dark", dark);
  // Native controls (select popups, scrollbars) follow the effective light/dark.
  root.style.colorScheme = dark ? "dark" : "light";
  root.style.fontSize = prefs.font_size ? `${prefs.font_size}px` : "";
  if (prefs.font_family && prefs.font_family !== "default") root.style.setProperty("--font-body", FONT_STACKS[prefs.font_family]);
  else root.style.removeProperty("--font-body");
}

export function readCachedPreferences(): UiPreferences | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    return raw ? sanitize(JSON.parse(raw)) : null;
  } catch {
    return null;
  }
}
export function cachePreferences(p: UiPreferences | null): void {
  try {
    if (p && Object.keys(sanitize(p)).length) localStorage.setItem(CACHE_KEY, JSON.stringify(sanitize(p)));
    else localStorage.removeItem(CACHE_KEY);
  } catch {
    /* storage unavailable */
  }
}
