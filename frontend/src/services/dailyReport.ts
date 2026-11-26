import { api } from "@/services/api";

// Roadmap PR30 (D5/D6): daily shift summary workbook and printable daily
// forms. Both endpoints are read-only; `grace_minutes` is the D6 attribution
// window (default 60, 0 = strict clock cut).
export type DailyFormKind = "dispatch" | "receipt" | "both";
export type DailyFormShift = "day" | "night" | "both";

export const DEFAULT_GRACE_MINUTES = 60;
export const MAX_GRACE_MINUTES = 240;

function save(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export async function downloadDailySummary(date: string, graceMinutes: number): Promise<void> {
  const resp = await api.get("/reports/daily-summary.xlsx", {
    params: { date, grace_minutes: graceMinutes },
    responseType: "blob",
  });
  save(resp.data as Blob, `รายงานรับ-ส่งเครื่อง-${date}.xlsx`);
}

// Opens the PDF in a new tab so the operator can print it; falls back to a
// download when the browser blocks the pop-up.
export async function printDailyForm(date: string, kind: DailyFormKind,
  graceMinutes: number,
  shift: DailyFormShift = "both",
): Promise<void> {
  const resp = await api.get("/reports/daily-forms.pdf", {
    params: { date, kind, shift, grace_minutes: graceMinutes },
    responseType: "blob",
  });
  const blob = new Blob([resp.data as Blob], { type: "application/pdf" });
  const url = URL.createObjectURL(blob);
  const win = window.open(url, "_blank");
  if (!win) {
    save(blob, `แบบบันทึกการเบิก-จ่าย-${date}-${shift}-${kind}.pdf`);
  }
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
