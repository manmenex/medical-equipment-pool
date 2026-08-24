import type {
  ReconciliationDisposition,
  ReconciliationFindingCode,
  ReconciliationRunStatus,
  ReconciliationSeverity,
} from "@/types/reconciliation";

// Roadmap PR22F -- centralized here (mirroring utils/legacyImportLabels.ts's
// established pattern) so every reconciliation screen renders the same
// Thai label/color for the same backend value. UI labels only -- never
// change or infer backend values from these.

export const RECONCILIATION_RUN_STATUS_LABELS: Record<ReconciliationRunStatus, string> = {
  pending: "รอประมวลผล",
  running: "กำลังประมวลผล",
  completed: "ประมวลผลเสร็จ",
  failed: "ประมวลผลไม่สำเร็จ",
};

export const RECONCILIATION_RUN_STATUS_COLORS: Record<ReconciliationRunStatus, string> = {
  pending: "bg-status-out_of_service/15 text-status-out_of_service",
  running: "bg-status-calibration/15 text-status-calibration",
  completed: "bg-status-available/15 text-status-available",
  failed: "bg-status-repair/15 text-status-repair",
};

export const RECONCILIATION_SEVERITY_LABELS: Record<ReconciliationSeverity, string> = {
  high: "สูง",
  medium: "ปานกลาง",
  low: "ต่ำ",
};

export const RECONCILIATION_SEVERITY_COLORS: Record<ReconciliationSeverity, string> = {
  high: "bg-status-repair/15 text-status-repair",
  medium: "bg-status-pm/15 text-status-pm",
  low: "bg-status-out_of_service/15 text-status-out_of_service",
};

// OD-PR22-2's closed four-value disposition vocabulary. "open" is a
// frontend-only UI key for the undispositioned (NULL) state, matching
// the backend's own "open"/"null" filter convention -- never sent as an
// actual disposition value.
export const RECONCILIATION_DISPOSITION_LABELS: Record<ReconciliationDisposition, string> = {
  confirmed_valid: "ยืนยันว่าข้อมูลถูกต้อง",
  confirmed_duplicate: "ยืนยันว่าเป็นข้อมูลซ้ำ",
  accepted_unresolved: "ยอมรับว่ายังไม่สามารถแก้ไขได้",
  requires_correction: "ต้องดำเนินการแก้ไข",
};

export const RECONCILIATION_DISPOSITION_FILTER_LABELS: Record<"open" | ReconciliationDisposition, string> = {
  open: "ยังไม่ตรวจ",
  confirmed_valid: "ยืนยันถูกต้อง",
  confirmed_duplicate: "ยืนยันข้อมูลซ้ำ",
  accepted_unresolved: "ยอมรับว่ายังแก้ไม่ได้",
  requires_correction: "ต้องแก้ไข",
};

export const RECONCILIATION_DISPOSITION_COLORS: Record<ReconciliationDisposition, string> = {
  confirmed_valid: "bg-status-available/15 text-status-available",
  confirmed_duplicate: "bg-status-out_of_service/15 text-status-out_of_service",
  accepted_unresolved: "bg-status-pm/15 text-status-pm",
  requires_correction: "bg-status-repair/15 text-status-repair",
};

// Roadmap PR22C's current rule taxonomy (app.models.legacy_reconciliation
// .RECONCILIATION_FINDING_CODES) -- reference only, not DB-enforced on
// the backend, so this frontend label map must degrade safely (never
// hard-fail) for a code it does not yet know about.
const RECONCILIATION_FINDING_CODE_LABELS: Record<string, string> = {
  EQUIPMENT_IDENTITY: "ข้อมูลระบุตัวเครื่องมือไม่ตรงกัน",
  SOURCE_PROVENANCE: "ไม่พบที่มาของข้อมูลเดิม",
  DUPLICATE_EXACT: "ข้อมูลซ้ำซ้อนทั้งหมด",
  DUPLICATE_SUSPECTED: "สงสัยว่าข้อมูลซ้ำซ้อน",
  CHRONOLOGY_ANOMALY: "ลำดับเวลาผิดปกติ",
  CURRENT_STATE_MISMATCH: "สถานะปัจจุบันไม่ตรงกับข้อมูลเดิม",
  WARD_TRACEABILITY_GAP: "ไม่สามารถตรวจสอบย้อนกลับหอผู้ป่วยได้",
  BME_TRACEABILITY_GAP: "ไม่สามารถตรวจสอบย้อนกลับผู้ดำเนินการ (BME) ได้",
  PAIRING_CANDIDATE: "รายการที่อาจจับคู่ได้",
};

// Never hard-fails on an unknown/future backend code (§16 of the task) --
// falls back to the raw backend code string, since PR22C's taxonomy is
// intentionally evolvable without a matching frontend release.
export function reconciliationFindingCodeLabel(code: ReconciliationFindingCode): string {
  return RECONCILIATION_FINDING_CODE_LABELS[code] ?? code;
}
