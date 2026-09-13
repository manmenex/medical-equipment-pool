import type {
  CutoverGateCode,
  CutoverGateItemCategory,
  CutoverGateStatus,
  CutoverGoNoGoDecisionValue,
  CutoverRunStatus,
} from "@/types/cutoverReadiness";

// Roadmap PR23E -- centralized here (mirroring utils/reconciliationLabels.ts's
// established pattern) so every cutover-readiness screen renders the same
// Thai label/color for the same backend value. UI labels only -- never
// change or infer backend values from these.

export const CUTOVER_RUN_STATUS_LABELS: Record<CutoverRunStatus, string> = {
  pending: "รอดำเนินการ",
  running: "กำลังดำเนินการ",
  completed: "บันทึกหลักฐานครบถ้วน",
  failed: "ไม่สำเร็จ",
};

export const CUTOVER_RUN_STATUS_COLORS: Record<CutoverRunStatus, string> = {
  pending: "bg-status-out_of_service/15 text-status-out_of_service",
  running: "bg-status-calibration/15 text-status-calibration",
  completed: "bg-status-available/15 text-status-available",
  failed: "bg-status-repair/15 text-status-repair",
};

// design §12 -- verify against docs/design/PR23_CUTOVER_READINESS_PLAN.md
// before changing. Never expose only the bare letter to an operator.
export const CUTOVER_GATE_LABELS: Record<CutoverGateCode, string> = {
  A: "ความพร้อมของระบบ/ฐานข้อมูล",
  B: "ข้อมูลทะเบียนเครื่องมือ",
  C: "ประวัติข้อมูลเดิม",
  D: "การตรวจสอบและรับรองข้อมูล",
  E: "สถานะเครื่องมือปัจจุบัน",
  F: "ความพร้อมด้านปฏิบัติการ",
};

export const CUTOVER_GATE_CATEGORY_LABELS: Record<CutoverGateItemCategory, string> = {
  blocker: "ตัวบล็อก",
  warning: "ต้องรับทราบ",
  info: "ข้อมูล",
};

export const CUTOVER_GATE_CATEGORY_COLORS: Record<CutoverGateItemCategory, string> = {
  blocker: "bg-status-repair/15 text-status-repair",
  warning: "bg-status-pm/15 text-status-pm",
  info: "bg-status-out_of_service/15 text-status-out_of_service",
};

export const CUTOVER_GATE_STATUS_LABELS: Record<CutoverGateStatus, string> = {
  blocker: "พบตัวบล็อก",
  warning: "มีรายการต้องรับทราบ",
  satisfied: "ผ่านการตรวจสอบอัตโนมัติ",
};

export const CUTOVER_GATE_STATUS_COLORS: Record<CutoverGateStatus, string> = {
  blocker: "bg-status-repair/15 text-status-repair",
  warning: "bg-status-pm/15 text-status-pm",
  satisfied: "bg-status-available/15 text-status-available",
};

export const CUTOVER_DECISION_LABELS: Record<CutoverGoNoGoDecisionValue, string> = {
  GO: "อนุมัติเปลี่ยนระบบ (GO)",
  NO_GO: "ไม่อนุมัติเปลี่ยนระบบ (NO-GO)",
};

export const CUTOVER_DECISION_COLORS: Record<CutoverGoNoGoDecisionValue, string> = {
  GO: "bg-status-available/15 text-status-available",
  NO_GO: "bg-status-repair/15 text-status-repair",
};
