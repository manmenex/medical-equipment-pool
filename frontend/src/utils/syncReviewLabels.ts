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
  OP_TOO_OLD: "รายการเกิดขึ้นนานเกิน 7 วันก่อนส่งถึงระบบ ต้องให้เจ้าหน้าที่ยืนยันเวลาก่อนบันทึก",
  EQUIPMENT_NOT_AVAILABLE: "อุปกรณ์ไม่อยู่ในสถานะที่เบิกได้ในขณะที่ส่งรายการ",
  DISPATCH_STATUS_WARNING: "เครื่องนี้ถูกจ่ายไปแล้วโดยยังไม่บันทึกรับคืน หรือถูกแจ้งเสีย ในขณะที่ส่งรายการ ต้องให้เจ้าหน้าที่ตรวจสอบและยืนยัน",
  DISPATCH_WARNING_STALE: "สถานะการจ่ายเครื่องเปลี่ยนไปหลังแสดงคำเตือน ต้องให้เจ้าหน้าที่ตรวจสอบอีกครั้ง",
  EQUIPMENT_STATUS_CHANGED: "สถานะเครื่องเปลี่ยนไประหว่างบันทึก ต้องให้เจ้าหน้าที่ตรวจสอบอีกครั้ง",
  TRANSACTION_CLOSED_BY_REDISPATCH: "รายการนี้ถูกปิดเพราะมีการจ่ายเครื่องใหม่แล้ว",
  EQUIPMENT_NOT_FOUND: "ไม่พบอุปกรณ์ในระบบ",
  TRANSACTION_NOT_FOUND: "ไม่พบรายการเบิกที่อ้างถึง",
  TRANSACTION_ALREADY_RETURNED: "รายการเบิกนี้มีการรับคืนแล้ว",
  RECEIPT_RACE_LOST: "มีการรับคืนรายการนี้พร้อมกันจากอีกที่หนึ่ง",
  DEPENDENCY_MISSING: "ไม่พบรายการเบิกที่รายการรับคืนนี้อ้างถึงในระบบ",
  FORBIDDEN: "ผู้บันทึกไม่มีสิทธิ์ในขณะที่ส่งรายการ (ผู้ดูแลระบบเท่านั้นที่ตรวจสอบได้)",
};

export function resultCodeLabel(code: string | null): string {
  if (!code) return "รอการตรวจสอบ";
  return RESULT_CODE_LABELS[code] ?? "ไม่สามารถบันทึกรายการได้ ต้องให้เจ้าหน้าที่ตรวจสอบ";
}
