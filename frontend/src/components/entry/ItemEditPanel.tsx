import type { ReactNode } from "react";

import { checkResults } from "@/services/checks";
import type { Checks } from "@/types";

/** ✓✓✓ (green) / ✗ (orange) per check; compact summary for a row. */
export function CheckGlyphs({ checks }: { checks: Checks | null }) {
  if (!checks) return null;
  return (
    <span aria-label="ผลการตรวจ" className="whitespace-nowrap text-xs tracking-tight">
      {checkResults(checks).map((ok, i) => (
        <span key={i} className={ok ? "text-status-available" : "font-bold text-orange-400"}>
          {ok ? "✓" : "✗"}
        </span>
      ))}
    </span>
  );
}

interface ItemEditPanelProps {
  bcm: string;
  name: string;
  statusLine?: ReactNode;
  onRemove: () => void;
  onDone: () => void;
  children: ReactNode;
  /**
   * Roadmap PR29 slot: the optional patient HN field is added here by PR29
   * (dispatch only). Intentionally empty in PR27/PR28 -- do not add an HN
   * input before PR29 and its Governance safeguards (masking, encryption).
   */
  extraSlot?: ReactNode;
}

// Inline edit panel (blue border) shared by the dispatch and receipt screens.
export function ItemEditPanel({ bcm, name, statusLine, onRemove, onDone, children, extraSlot }: ItemEditPanelProps) {
  return (
    <div role="group" aria-label={`แก้ไข ${bcm}`} className="surface flex flex-col gap-3 rounded-lg border-2 border-status-borrowed p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 text-sm">
          <div className="font-semibold">{bcm}</div>
          <div className="truncate text-xs text-[var(--text-muted)]">{name}</div>
          {statusLine && <div className="text-xs">{statusLine}</div>}
        </div>
        <button
          type="button"
          onClick={onRemove}
          className="shrink-0 whitespace-nowrap rounded-md border border-status-repair px-2 py-1 text-[13px] text-status-repair"
        >
          ลบออก
        </button>
      </div>
      {children}
      {extraSlot}
      <button type="button" onClick={onDone} className="rounded-lg bg-status-borrowed py-2 text-sm font-medium text-white">
        เสร็จ
      </button>
    </div>
  );
}
