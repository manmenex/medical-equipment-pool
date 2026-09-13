import axios from "axios";

import { apiErrorCode, apiErrorMessage } from "@/services/api";

// Roadmap PR20F: centralized mapping from the real backend's stable
// `code` field (docs/api/ERROR_CODES.md) to the small set of UX
// treatments the Equipment Master real workflow needs. Every page goes
// through this -- no scattered string comparisons against `code`/`detail`
// on individual pages.

export type EquipmentMasterImportErrorKind =
  | "stale_plan"
  | "no_confirmed_plan"
  | "plan_not_found"
  | "session_not_found"
  | "invalid_state"
  | "attempt_in_progress"
  | "recovery_required"
  | "execution_failed"
  | "permission_denied"
  | "network"
  | "server_error"
  | "generic";

export interface EquipmentMasterImportErrorInfo {
  code: string | undefined;
  kind: EquipmentMasterImportErrorKind;
  message: string;
}

// Roadmap PR20D/PR20E §19/§20: 409 IMPORT_DRY_RUN_PLAN_STALE is a single,
// unified contract on the backend -- it deliberately never distinguishes
// "plan missing" from "foreign plan," "superseded," "session moved on,"
// or "dry-run failed." This client preserves that same non-distinction:
// exactly one Thai message, one recommended action (regenerate the
// dry-run), never an attempt to infer which specific sub-case occurred.
const STALE_PLAN_MESSAGE =
  "แผนการนำเข้าที่ตรวจสอบไว้ไม่สามารถใช้งานได้แล้ว (อาจมีการทดลองนำเข้าใหม่หรือรายการมีการเปลี่ยนแปลง) กรุณาทดลองนำเข้าใหม่อีกครั้งแล้วตรวจสอบก่อนยืนยัน";

export function describeEquipmentMasterImportError(error: unknown): EquipmentMasterImportErrorInfo {
  const code = apiErrorCode(error);
  const fallbackMessage = apiErrorMessage(error);

  if (axios.isAxiosError(error) && !error.response) {
    return { code, kind: "network", message: "ไม่สามารถเชื่อมต่อกับระบบได้ กรุณาตรวจสอบการเชื่อมต่อแล้วลองใหม่" };
  }

  switch (code) {
    case "IMPORT_DRY_RUN_PLAN_STALE":
      return { code, kind: "stale_plan", message: STALE_PLAN_MESSAGE };
    case "IMPORT_NO_CONFIRMED_PLAN":
      return {
        code,
        kind: "no_confirmed_plan",
        message: "ยังไม่ได้ยืนยันแผนการนำเข้า กรุณายืนยันแผนการนำเข้าก่อนดำเนินการนำเข้าจริง",
      };
    case "IMPORT_DRY_RUN_PLAN_NOT_FOUND":
      return { code, kind: "plan_not_found", message: "ยังไม่มีแผนการนำเข้าสำหรับรายการนี้ กรุณาทดลองนำเข้าก่อน" };
    case "IMPORT_SESSION_NOT_FOUND":
      return { code, kind: "session_not_found", message: "ไม่พบรายการนำเข้าข้อมูลนี้" };
    case "IMPORT_SESSION_INVALID_STATE":
      return { code, kind: "invalid_state", message: fallbackMessage };
    case "IMPORT_ATTEMPT_IN_PROGRESS":
      return {
        code,
        kind: "attempt_in_progress",
        message: "มีการดำเนินการอยู่แล้วสำหรับรายการนี้ กรุณารอสักครู่แล้วลองใหม่",
      };
    case "IMPORT_RECOVERY_REQUIRED":
      return {
        code,
        kind: "recovery_required",
        message: "การดำเนินการก่อนหน้าค้างอยู่ กรุณากู้คืนสถานะแล้วลองใหม่อีกครั้ง",
      };
    case "IMPORT_EXECUTION_FAILED":
      return {
        code,
        kind: "execution_failed",
        message:
          "การนำเข้าข้อมูลจริงล้มเหลว (เช่น ข้อมูลเครื่องมือมีการเปลี่ยนแปลงหลังทดลองนำเข้า) ไม่มีข้อมูลถูกบันทึกลงระบบ กรุณาทดลองนำเข้าใหม่แล้วตรวจสอบอีกครั้ง",
      };
    default:
      break;
  }

  if (axios.isAxiosError(error)) {
    const status = error.response?.status;
    if (status === 401 || status === 403) {
      return { code, kind: "permission_denied", message: "คุณไม่มีสิทธิ์ดำเนินการนี้" };
    }
    if (status !== undefined && status >= 500) {
      return { code, kind: "server_error", message: fallbackMessage };
    }
  }

  return { code, kind: "generic", message: fallbackMessage };
}

// §19/§20/§25/§26: every one of these kinds means the same thing to the
// operator -- the reviewed plan can no longer be trusted and a fresh
// dry-run is required before trying again. Never auto-retried, never a
// silent refresh of expected_version.
export function requiresFreshDryRun(kind: EquipmentMasterImportErrorKind | LegacyHistoryImportErrorKind): boolean {
  return kind === "stale_plan" || kind === "no_confirmed_plan" || kind === "execution_failed";
}

// Roadmap PR21E: Legacy Transaction History reuses every kind above
// (the underlying session/plan lifecycle is the same generic PR19
// infrastructure both datasets share) plus two authority-specific kinds
// from backend/app/api/v1/legacy_migration_authorities.py. A new sibling
// function, not a rename/generalization of describeEquipmentMasterImportError
// above -- minimizes regression risk to the already-shipped Equipment
// Master workflow.
export type LegacyHistoryImportErrorKind =
  | EquipmentMasterImportErrorKind
  | "authority_not_found"
  | "authority_scope_conflict";

export interface LegacyHistoryImportErrorInfo {
  code: string | undefined;
  kind: LegacyHistoryImportErrorKind;
  message: string;
}

export function describeLegacyHistoryImportError(error: unknown): LegacyHistoryImportErrorInfo {
  const code = apiErrorCode(error);

  if (code === "LEGACY_MIGRATION_AUTHORITY_NOT_FOUND") {
    return {
      code,
      kind: "authority_not_found",
      message: "ยังไม่มีการอนุมัติไฟล์นี้สำหรับการนำเข้า",
    };
  }
  if (code === "LEGACY_MIGRATION_AUTHORITY_SCOPE_CONFLICT") {
    return {
      code,
      kind: "authority_scope_conflict",
      message: "checksum ของไฟล์นี้ได้รับการอนุมัติภายใต้ขอบเขตอื่นไปแล้ว ไม่สามารถอนุมัติซ้ำภายใต้ขอบเขตนี้ได้",
    };
  }

  return describeEquipmentMasterImportError(error);
}
