import type { EquipmentStatus } from "@/types";

const LABELS: Record<EquipmentStatus, string> = {
  available: "พร้อมใช้งาน",
  borrowed: "ถูกยืม",
  cleaning: "ทำความสะอาด",
  pm: "PM",
  calibration: "สอบเทียบ",
  repair: "ซ่อม",
  out_of_service: "ปลดระวาง",
  lost: "สูญหาย",
};

const COLORS: Record<EquipmentStatus, string> = {
  available: "bg-status-available/15 text-status-available",
  borrowed: "bg-status-borrowed/15 text-status-borrowed",
  cleaning: "bg-status-cleaning/15 text-status-cleaning",
  pm: "bg-status-pm/15 text-status-pm",
  calibration: "bg-status-calibration/15 text-status-calibration",
  repair: "bg-status-repair/15 text-status-repair",
  out_of_service: "bg-status-out_of_service/15 text-status-out_of_service",
  lost: "bg-status-lost/15 text-status-lost",
};

export function StatusBadge({ status }: { status: EquipmentStatus }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${COLORS[status]}`}>
      {LABELS[status]}
    </span>
  );
}
