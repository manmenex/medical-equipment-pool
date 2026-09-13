import type { ImportFinding, ImportResultSummary } from "@/types/legacyImport";
import type { ImportSessionOut, ValidationFindingOut } from "@/types/legacyImportApi";

// Roadmap PR20F/PR21E: thin, field-for-field presentational mappers from
// the real backend-shaped types (types/legacyImportApi.ts) to the shared
// display types both real workflows use (types/legacyImport.ts) -- reused
// here only where those display types are a faithful 1:1 mirror of real
// ImportSessionOut/ValidationFindingOut fields, never for the dry-run/plan
// shapes each dataset's own dedicated summary component renders instead
// (EquipmentMasterDryRunPlanSummary.tsx / LegacyHistoryDryRunPlanSummary.tsx).
// No business decision is made here -- every field is a straight rename
// (snake_case -> camelCase) or a direct pass-through.

export function toImportFinding(finding: ValidationFindingOut): ImportFinding {
  return {
    id: finding.id,
    rowNumber: finding.row_number,
    field: finding.field,
    errorCode: finding.error_code,
    message: finding.message,
    severity: finding.severity,
  };
}

const RESULT_STATUSES = new Set(["completed", "failed", "cancelled"]);

export function toResultSummary(session: ImportSessionOut): ImportResultSummary | null {
  if (!RESULT_STATUSES.has(session.status)) return null;
  return {
    status: session.status as ImportResultSummary["status"],
    importedRows: session.imported_rows,
    terminalAt: session.terminal_at,
    sessionId: session.id,
  };
}
