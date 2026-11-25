import type { Shift } from "@/types";

// Roadmap PR26: Day 08:00-20:00, Night 20:00-08:00 (local clock). Display
// only; the backend remains the authority for stored business_date/shift.
export function currentShift(now: Date): Shift {
  const h = now.getHours();
  return h >= 8 && h < 20 ? "day" : "night";
}

export const SHIFT_LABELS: Record<Shift, { label: string; hours: string }> = {
  day: { label: "Day", hours: "08:00-20:00" },
  night: { label: "Night", hours: "20:00-08:00" },
};
