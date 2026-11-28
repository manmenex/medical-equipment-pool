import type { Shift } from "@/types";

// Roadmap PR26: Day 08:00-20:00, Night 20:00-08:00 (local clock). Display
// only; the backend remains the authority for stored business_date/shift.
export function currentShift(now: Date): Shift {
  const h = now.getHours();
  return h >= 8 && h < 20 ? "day" : "night";
}

// Roadmap PR30: PR16 business_date is shift-start anchored, so before 08:00
// the current (Night) shift started on the previous calendar day. Returns
// YYYY-MM-DD from the local clock. Default only; the backend decides.
export function currentBusinessDate(now: Date): string {
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (now.getHours() < 8) d.setDate(d.getDate() - 1);
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

export const SHIFT_LABELS: Record<Shift, { label: string; hours: string }> = {
  day: { label: "Day", hours: "08:00-20:00" },
  night: { label: "Night", hours: "20:00-08:00" },
};
