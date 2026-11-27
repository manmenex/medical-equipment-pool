import type { EquipmentStatus } from "@/types";

// Roadmap PR6: 4-state model. A `legacy_status: "cleaning"` row is plain
// AVAILABLE_AT_POOL equipment -- it renders with this same label/color,
// never a distinct or defect-styled badge (owner-confirmed cleaning
// retirement: see docs/audits/04-consolidated-implementation-plan.md PR6).
// Exported (Dashboard UX follow-up review, PR40-L1) so any other status-count display
// -- e.g. DashboardPage.tsx -- reuses this single source instead of
// duplicating the same four literals and risking future drift.
export const STATUS_LABELS: Record<EquipmentStatus, string> = {
  available_at_pool: "พร้อมใช้งาน",
  issued_to_ward: "จ่ายให้ Ward แล้ว",
  unavailable_defective: "ไม่พร้อมใช้งาน",
  decommissioned: "ปลดระวางถาวร",
};

// D28: a voided TRANSACTION status (never an equipment state).
const VOIDED_LABEL = "ยกเลิกแล้ว";

const COLORS: Record<EquipmentStatus | "voided", string> = {
  voided: "bg-[var(--border)]/40 text-[var(--text-muted)] line-through",
  available_at_pool: "bg-status-available/15 text-status-available",
  issued_to_ward: "bg-status-borrowed/15 text-status-borrowed",
  unavailable_defective: "bg-status-repair/15 text-status-repair",
  decommissioned: "bg-status-out_of_service/15 text-status-out_of_service",
};

export function StatusBadge({ status }: { status: EquipmentStatus | "voided" }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${COLORS[status]}`}>
      {status === "voided" ? VOIDED_LABEL : STATUS_LABELS[status]}
    </span>
  );
}
