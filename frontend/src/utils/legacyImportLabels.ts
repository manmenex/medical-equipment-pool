import type { ImportCategory, ImportFindingSeverity, ImportSessionStatus } from "@/types/legacyImport";

// Roadmap PR20F/PR21E: centralized here (rather than repeated per
// component) so every screen renders the same Thai label/color for the
// same value.

export const IMPORT_CATEGORY_LABELS: Record<ImportCategory, string> = {
  equipment_master: "ข้อมูลหลักเครื่องมือ (Equipment Master)",
  legacy_transaction_history: "ประวัติการรับ-ส่งเครื่องมือเดิม",
};

// Labels for the real 11-value backend status enum
// (backend/app/models/import_session.py's ck_import_sessions_status).
export const IMPORT_STATUS_LABELS: Record<ImportSessionStatus, string> = {
  created: "สร้างรายการแล้ว",
  validating: "กำลังตรวจสอบข้อมูล",
  validated: "ตรวจสอบข้อมูลแล้ว",
  validation_failed: "ตรวจสอบข้อมูลไม่ผ่าน",
  dry_run_running: "กำลังทดลองนำเข้าโดยไม่บันทึก",
  dry_run_completed: "ทดลองนำเข้าโดยไม่บันทึกแล้ว รอการยืนยัน",
  dry_run_failed: "ทดลองนำเข้าไม่สำเร็จ",
  executing: "กำลังนำเข้าข้อมูล",
  completed: "นำเข้าสำเร็จ",
  failed: "นำเข้าไม่สำเร็จ",
  cancelled: "ยกเลิกแล้ว",
};

export const IMPORT_STATUS_COLORS: Record<ImportSessionStatus, string> = {
  created: "bg-status-out_of_service/15 text-status-out_of_service",
  validating: "bg-status-borrowed/15 text-status-borrowed",
  validated: "bg-status-borrowed/15 text-status-borrowed",
  validation_failed: "bg-status-repair/15 text-status-repair",
  dry_run_running: "bg-status-calibration/15 text-status-calibration",
  dry_run_completed: "bg-status-pm/15 text-status-pm",
  dry_run_failed: "bg-status-repair/15 text-status-repair",
  executing: "bg-status-calibration/15 text-status-calibration",
  completed: "bg-status-available/15 text-status-available",
  failed: "bg-status-repair/15 text-status-repair",
  cancelled: "bg-status-out_of_service/15 text-status-out_of_service",
};

export const IMPORT_FINDING_SEVERITY_LABELS: Record<ImportFindingSeverity, string> = {
  error: "ไม่ถูกต้อง",
  warning: "คำเตือน",
};

export const IMPORT_FINDING_SEVERITY_COLORS: Record<ImportFindingSeverity, string> = {
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

// File-type gate for the create-session flow (LegacyImportFileDropzone).
// The `accept` attribute on the underlying <input type="file"> is
// usability-only -- it is not enforced by the browser for drag-and-drop,
// and can be bypassed via a file picker's "all files" option, so it must
// never be the only check.
const ALLOWED_FILE_EXTENSIONS = [".xlsx"];

export function isAllowedImportFile(file: File): boolean {
  const lowerName = file.name.toLowerCase();
  return ALLOWED_FILE_EXTENSIONS.some((ext) => lowerName.endsWith(ext));
}

export const IMPORT_FILE_TYPE_ERROR_MESSAGE = "รองรับเฉพาะไฟล์ .xlsx เท่านั้น กรุณาเลือกไฟล์ใหม่";
