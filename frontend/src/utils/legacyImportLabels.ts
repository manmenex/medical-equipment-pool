import type { ImportCategory, ImportIssueSeverity, ImportSessionStatus } from "@/types/legacyImport";

// PR19B skeleton only -- see types/legacyImport.ts's file-level note.
// Centralized here (rather than repeated per component) so every screen
// renders the same Thai label/color for the same provisional value.

export const IMPORT_CATEGORY_LABELS: Record<ImportCategory, string> = {
  equipment_master: "ข้อมูลหลักเครื่องมือ (Equipment Master)",
  receive_history: "ประวัติการรับคืน (Receive History)",
  issue_history: "ประวัติการเบิก (Issue History)",
};

export const IMPORT_STATUS_LABELS: Record<ImportSessionStatus, string> = {
  uploaded: "อัปโหลดไฟล์แล้ว",
  validating: "กำลังตรวจสอบข้อมูล",
  validated: "ตรวจสอบข้อมูลแล้ว",
  dry_run_completed: "ทดลองนำเข้าโดยไม่บันทึกแล้ว",
  awaiting_confirmation: "รอการยืนยันนำเข้า",
  completed: "นำเข้าสำเร็จ",
  completed_with_warnings: "นำเข้าสำเร็จ (มีคำเตือน)",
  failed: "นำเข้าไม่สำเร็จ",
  cancelled: "ยกเลิกแล้ว",
};

export const IMPORT_STATUS_COLORS: Record<ImportSessionStatus, string> = {
  uploaded: "bg-status-out_of_service/15 text-status-out_of_service",
  validating: "bg-status-borrowed/15 text-status-borrowed",
  validated: "bg-status-borrowed/15 text-status-borrowed",
  dry_run_completed: "bg-status-calibration/15 text-status-calibration",
  awaiting_confirmation: "bg-status-pm/15 text-status-pm",
  completed: "bg-status-available/15 text-status-available",
  completed_with_warnings: "bg-status-pm/15 text-status-pm",
  failed: "bg-status-repair/15 text-status-repair",
  cancelled: "bg-status-out_of_service/15 text-status-out_of_service",
};

export const IMPORT_ISSUE_SEVERITY_LABELS: Record<ImportIssueSeverity, string> = {
  error: "ไม่ถูกต้อง",
  warning: "คำเตือน",
};

export const IMPORT_ISSUE_SEVERITY_COLORS: Record<ImportIssueSeverity, string> = {
  error: "bg-status-repair/15 text-status-repair",
  warning: "bg-status-pm/15 text-status-pm",
};

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unitIndex]}`;
}
