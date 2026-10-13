export const DISMISS_REASON_LABELS: Record<string, string> = {
  already_recorded: "บันทึกไว้แล้ว",
  duplicate_physical_entry: "บันทึกซ้ำจากการกรอกหลายครั้ง",
  not_real: "ไม่ใช่รายการจริง",
  handled_elsewhere: "ดำเนินการด้วยวิธีอื่นแล้ว",
};

export const OP_TYPE_LABELS: Record<string, string> = {
  dispatch: "เบิก",
  receipt: "รับคืน",
};

export function opTypeLabel(t: string): string {
  return OP_TYPE_LABELS[t] ?? t;
}

const RESULT_CODE_LABELS: Record<string, string> = {
  OP_TOO_OLD: "รายการค้างส่งนานเกินกำหนด (เกิน 48 ชั่วโมง) ต้องให้เจ้าหน้าที่ตรวจสอบเวลาก่อนบันทึก",
  EQUIPMENT_NOT_AVAILABLE: "อุปกรณ์ไม่อยู่ในสถานะที่เบิกได้ในขณะที่ส่งรายการ",
  EQUIPMENT_NOT_FOUND: "ไม่พบอุปกรณ์ในระบบ",
  TRANSACTION_NOT_FOUND: "ไม่พบรายการเบิกที่อ้างถึง",
  TRANSACTION_ALREADY_RETURNED: "รายการเบิกนี้มีการรับคืนแล้ว",
  RECEIPT_RACE_LOST: "มีการรับคืนรายการนี้พร้อมกันจากอีกที่หนึ่ง",
  DEPENDENCY_MISSING: "รายการที่ต้องมาก่อนยังไม่ถูกส่งหรือยังไม่ได้รับการแก้ไข",
  FORBIDDEN: "ผู้บันทึกไม่มีสิทธิ์ในขณะที่ส่งรายการ (ผู้ดูแลระบบเท่านั้นที่ตรวจสอบได้)",
};

export function resultCodeLabel(code: string | null): string {
  if (!code) return "รอการตรวจสอบ";
  return RESULT_CODE_LABELS[code] ?? "ไม่สามารถบันทึกรายการได้ ต้องให้เจ้าหน้าที่ตรวจสอบ";
}
