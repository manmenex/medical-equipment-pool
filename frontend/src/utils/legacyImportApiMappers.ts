import type { ImportFinding, ImportResultSummary, ImportSessionStatus as MockImportSessionStatus } from "@/types/legacyImport";
import type { ImportSessionOut, ValidationFindingOut } from "@/types/legacyImportApi";

// Roadmap PR20F: thin, field-for-field presentational mappers from the
// real backend-shaped types (types/legacyImportApi.ts) to the existing,
// already-accurate, already-tested display types the PR19B skeleton
// introduced (types/legacyImport.ts) -- reused here only where those
// display types are a faithful 1:1 mirror of real ImportSessionOut/
// ValidationFindingOut fields (documented as such in that file's own
// comments), never for the dry-run/plan shapes that file's mock
// invented as a stand-in before a real DryRunPlan contract existed (see
// components/EquipmentMasterDryRunPlanSummary.tsx for that real shape
// instead). No business decision is made here -- every field is a
// straight rename (snake_case -> camelCase) or a direct pass-through.

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

// The real backend's 11-value status enum is identical in name and
// membership to the mock's own ImportSessionStatus (types/legacyImport.ts)
// -- both mirror the same ck_import_sessions_status CHECK constraint --
// so this is a type-level identity, not a remapping.
export function toMockStatus(status: ImportSessionOut["status"]): MockImportSessionStatus {
  return status;
}
