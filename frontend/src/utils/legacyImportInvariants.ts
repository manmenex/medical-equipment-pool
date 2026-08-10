import type { ImportFinding, ImportFindingSeverity, ImportSessionDetail, ImportSessionStatus } from "@/types/legacyImport";

// Shared invariant helpers for PR19B mock/fixture data, derived from the
// merged PR19A backend contract (docs/design/PR19A_LEGACY_IMPORT_
// FOUNDATION_PLAN.md). Used both by legacyImportFixtures.ts (to construct
// fixtures that cannot drift from these rules) and by
// legacyImportFixtures.test.ts (to verify them). This module never talks
// to a real backend -- it only encodes the authoritative *shape* of that
// backend's data so this skeleton's own invented sample data stays honest.

// design §5: dry-run is reachable only from VALIDATED; execute only from
// DRY_RUN_COMPLETED. design §12/§13: a session reaches VALIDATED if and
// only if it has zero distinct rows with an ERROR-severity finding, and
// that "current validation snapshot" (total/valid/invalid/warning_rows)
// persists unchanged until the next successful validate re-promotes it
// (§12's "Promotion rule"). So every status below is reachable only while
// that promoted snapshot still reports invalid_rows === 0.
export const STATUSES_REQUIRING_ZERO_INVALID_ROWS: ReadonlySet<ImportSessionStatus> = new Set([
  "validated",
  "dry_run_running",
  "dry_run_completed",
  "dry_run_failed",
  "executing",
  "completed",
  "failed",
]);

// design §5/§18: the only three statuses that ever set terminal_at, and
// every session reaching one of them does set it.
export const TERMINAL_STATUSES: ReadonlySet<ImportSessionStatus> = new Set(["completed", "failed", "cancelled"]);

// design §12 "Distinct-row counting": invalid_rows/warning_rows are each a
// COUNT(DISTINCT row_number) over one severity -- independent projections,
// so one row may legitimately contribute to both.
export function countDistinctRowsBySeverity(findings: ImportFinding[], severity: ImportFindingSeverity): number {
  const rows = new Set<number>();
  for (const finding of findings) {
    if (finding.severity === severity && finding.rowNumber !== null) {
      rows.add(finding.rowNumber);
    }
  }
  return rows.size;
}

// Throws with a descriptive message the moment a fixture (or a
// dynamically-built mock session) violates the authoritative backend
// contract -- called at fixture-construction time so a bad fixture fails
// immediately and loudly (module load / factory call), not silently at
// render time.
export function assertImportSessionInvariants(detail: ImportSessionDetail): void {
  const { id, status, totalRows, validRows, invalidRows, warningRows, findings, resultSummary } = detail;

  const counters = [totalRows, validRows, invalidRows, warningRows];
  const allNull = counters.every((c) => c === null);
  const allSet = counters.every((c) => c !== null);
  if (!allNull && !allSet) {
    throw new Error(
      `[${id}] total/valid/invalid/warning rows must be all-null or all-set together ` +
        `(design §12/schema: populated only once a validate attempt has completed)`
    );
  }

  if (allSet) {
    // design §12: valid_rows = total_rows - invalid_rows. warning_rows is
    // an independent projection (a row may carry both an ERROR and a
    // WARNING finding) and must never be subtracted here too.
    if (validRows !== (totalRows as number) - (invalidRows as number)) {
      throw new Error(
        `[${id}] validRows (${validRows}) must equal totalRows (${totalRows}) - invalidRows (${invalidRows})`
      );
    }
    const derivedInvalid = countDistinctRowsBySeverity(findings, "error");
    const derivedWarning = countDistinctRowsBySeverity(findings, "warning");
    if (derivedInvalid !== invalidRows) {
      throw new Error(
        `[${id}] invalidRows (${invalidRows}) does not match distinct ERROR-severity rows in findings (${derivedInvalid})`
      );
    }
    if (derivedWarning !== warningRows) {
      throw new Error(
        `[${id}] warningRows (${warningRows}) does not match distinct WARNING-severity rows in findings (${derivedWarning})`
      );
    }
  }

  if (STATUSES_REQUIRING_ZERO_INVALID_ROWS.has(status)) {
    if ((invalidRows ?? 0) > 0) {
      throw new Error(
        `[${id}] status "${status}" requires invalidRows === 0 (design §5/§12/§13: dry-run/execute/completion ` +
          `are reachable only from a VALIDATED attempt with zero blocking errors)`
      );
    }
    if (findings.some((f) => f.severity === "error")) {
      throw new Error(
        `[${id}] status "${status}" must not show a blocking ERROR finding in its current validation snapshot`
      );
    }
  }

  if (TERMINAL_STATUSES.has(status)) {
    if (!resultSummary) {
      throw new Error(`[${id}] terminal status "${status}" must have a resultSummary (design §5/§18)`);
    }
    if (resultSummary.status !== status) {
      throw new Error(
        `[${id}] resultSummary.status (${resultSummary.status}) must match session status (${status})`
      );
    }
    if (resultSummary.terminalAt === null) {
      throw new Error(
        `[${id}] terminal status "${status}" must set terminalAt ` +
          `(design §5/§18: terminal_at is set only for, and always for, COMPLETED/FAILED/CANCELLED)`
      );
    }
    if (status === "completed" && resultSummary.importedRows === null) {
      throw new Error(`[${id}] a completed session must report a non-null importedRows`);
    }
    if ((status === "failed" || status === "cancelled") && resultSummary.importedRows !== null) {
      // Not a literal backend field constraint, but this skeleton's own
      // deliberate modeling choice: a FAILED execution rolls back every
      // domain write (design §19) and a CANCELLED session never reaches
      // execute at all (design §5's transition table) -- neither has a
      // real "rows imported" outcome to report, so this skeleton always
      // represents it as null rather than asserting a possibly-false 0.
      throw new Error(
        `[${id}] status "${status}" never executes successfully -- importedRows must be null, not ${resultSummary.importedRows}`
      );
    }
  } else if (resultSummary !== null) {
    throw new Error(`[${id}] non-terminal status "${status}" must not have a resultSummary`);
  }
}
