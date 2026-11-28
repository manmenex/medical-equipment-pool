import type { Checks, ChecklistKind, Cuffs, CuffType, CryoCuffChecks, StandardChecks } from "@/types";

// Roadmap PR28 (D4/D10): checklist item definitions (Thai labels from the paper forms).
export const STANDARD_ITEMS: { key: keyof Omit<StandardChecks, "kind">; label: string }[] = [
  { key: "screen_ok", label: "หน้าจอไม่แตกร้าว" },
  { key: "charger_ok", label: "สายชาร์จไม่ขาด" },
  { key: "clamp_ok", label: "Pole Clamp ไม่แตกหัก" },
];

export const CRYO_ITEMS: { key: keyof Omit<CryoCuffChecks, "kind" | "cuffs">; no: number; label: string; hint?: string }[] = [
  { key: "body_ok", no: 1, label: "ตัวเครื่อง ×1", hint: "ไม่แตกหัก เสียหาย" },
  { key: "charger_ok", no: 2, label: "สายชาร์จ ×1" },
  { key: "lid_with_charger_ok", no: 3, label: "ฝาปิดตัวเครื่อง แบบมีสายชาร์จ ×1" },
  { key: "lid_without_charger_ok", no: 4, label: "ฝาปิดตัวเครื่อง แบบไม่มีสายชาร์จ ×1" },
  { key: "hose_oring_ok", no: 5, label: "สายท่อน้ำและ O-Ring ×1", hint: "O-Ring บริเวณปลาย Hose ทั้งสองข้าง" },
  { key: "cuff_ok", no: 6, label: "Cuff", hint: "สภาพสมบูรณ์ ไม่มีฉีกขาด" },
];

export const CUFF_TYPES: { key: CuffType; label: string }[] = [
  { key: "back_hip_rib", label: "Back/Hip/Rib" },
  { key: "knee", label: "Knee" },
  { key: "shoulder", label: "Shoulder" },
  { key: "ankle", label: "Ankle" },
];

export const emptyCuffs = (): Cuffs => ({ back_hip_rib: 0, knee: 0, shoulder: 0, ankle: 0 });

export function defaultChecks(kind: ChecklistKind, cuffs?: Partial<Cuffs>): Checks {
  if (kind === "cryo_cuff") {
    return {
      kind,
      body_ok: true,
      charger_ok: true,
      lid_with_charger_ok: true,
      lid_without_charger_ok: true,
      hose_oring_ok: true,
      cuff_ok: true,
      cuffs: { ...emptyCuffs(), ...cuffs },
    };
  }
  return { kind: "standard", screen_ok: true, charger_ok: true, clamp_ok: true };
}

/** Boolean results in display order (3 for standard, 6 for Cryo-Cuff). */
export function checkResults(c: Checks): boolean[] {
  if (c.kind === "standard") return STANDARD_ITEMS.map((i) => c[i.key]);
  return CRYO_ITEMS.map((i) => c[i.key]);
}

export const hasAbnormal = (c: Checks): boolean => checkResults(c).some((ok) => !ok);

export const totalCuffs = (c: Partial<Cuffs> | null | undefined): number =>
  Object.values(c ?? {}).reduce<number>((a, n) => a + (n ?? 0), 0);

/** Thai message per batch/receipt/dispatch error code. */
const ERROR_TEXT: Record<string, string> = {
  EQUIPMENT_NOT_FOUND: "ไม่พบเครื่องมือ",
  EQUIPMENT_NOT_AVAILABLE: "เครื่องนี้ไม่พร้อมให้เบิก (ปลดระวางหรือมีการเบิกซ้อน)",
  DISPATCH_STATUS_WARNING: "สถานะเครื่องมีคำเตือน กรุณายืนยันอีกครั้ง",
  DISPATCH_WARNING_STALE: "สถานะเครื่องเปลี่ยนไปหลังแสดงคำเตือน ตรวจสอบสถานะล่าสุดแล้ว กรุณายืนยันอีกครั้ง",
  EQUIPMENT_STATUS_CHANGED: "สถานะเครื่องเปลี่ยนไประหว่างบันทึก กรุณายืนยันอีกครั้ง",
  CHECKLIST_KIND_MISMATCH: "ชนิดรายการตรวจไม่ตรงกับเครื่องนี้ กรุณาลบแล้วสแกนใหม่",
  TRANSACTION_NOT_FOUND: "เครื่องนี้ไม่ได้ถูกจ่ายออกไป ไม่พบรายการเบิก",
  TRANSACTION_ALREADY_RETURNED: "รายการนี้ถูกรับคืนไปแล้ว",
  TRANSACTION_CLOSED_BY_REDISPATCH: "รายการนี้ถูกปิดเพราะมีการจ่ายเครื่องใหม่แล้ว",
  RECEIPT_RACE_LOST: "มีคำขอรับเครื่องอื่นดำเนินการสำเร็จก่อน กรุณารีเฟรช",
  CUFF_RETURN_EXCEEDS_OUTSTANDING: "จำนวน Cuff ที่รับคืนมากกว่าจำนวนที่ค้างอยู่",
  CUFF_RECEIVE_NOT_ALLOWED: "เครื่องยังไม่ถูกรับคืน บันทึก Cuff พร้อมการรับเครื่อง",
  HN_UNAVAILABLE: "บันทึก HN ไม่ได้: ระบบยังไม่ได้ตั้งกุญแจเข้ารหัส HN (ลบ HN ออกแล้วบันทึกใหม่ หรือแจ้งผู้ดูแลระบบ)",
  INTERNAL_ERROR: "ระบบขัดข้อง กรุณาลองใหม่",
};

export function batchErrorText(code: string | undefined, fallback?: string): string {
  return (code && ERROR_TEXT[code]) || fallback || "บันทึกไม่สำเร็จ";
}
