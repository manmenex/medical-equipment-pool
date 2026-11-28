import { useEffect, useState } from "react";

import { currentShift, SHIFT_LABELS } from "@/utils/shift";

/** "Day · HH:MM" / "Night · HH:MM" (display only; the backend stamps the real time and shift). */
export function shiftChipText(now: Date): string {
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  return `${SHIFT_LABELS[currentShift(now)].label} · ${hh}:${mm}`;
}

export function ShiftChip() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(t);
  }, []);
  return (
    <span
      data-testid="shift-chip"
      className="whitespace-nowrap rounded-full bg-status-borrowed/15 px-2.5 py-0.5 text-xs font-medium text-status-borrowed"
    >
      {shiftChipText(now)}
    </span>
  );
}
