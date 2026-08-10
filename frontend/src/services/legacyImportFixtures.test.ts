import { describe, expect, it } from "vitest";

import { createMockImportSession, legacyImportSkeletonFixtures } from "@/services/legacyImportFixtures";
import {
  STATUSES_REQUIRING_ZERO_INVALID_ROWS,
  TERMINAL_STATUSES,
  assertImportSessionInvariants,
  countDistinctRowsBySeverity,
} from "@/utils/legacyImportInvariants";

// PR19B fixture-invariant tests (review finding PR80-H1): every mock/
// fixture session must obey the merged PR19A backend's real invariants
// (docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md §5/§12/§13/§18), not
// an invented approximation. legacyImportFixtures.ts already makes most of
// these violations structurally impossible (buildDetail/
// assertImportSessionInvariants runs at module load), but these tests
// exist so a future edit that bypasses that factory is still caught here.

describe("legacy import fixture invariants", () => {
  const fixtures = legacyImportSkeletonFixtures;

  it("seeds at least one fixture per status this skeleton demonstrates", () => {
    // Guards against silently losing coverage of a status if a fixture is
    // ever removed -- the remaining table-driven tests only assert
    // properties of whatever fixtures exist, they don't require any
    // particular status to be present.
    const statuses = new Set(fixtures.map((f) => f.status));
    expect(statuses.has("dry_run_completed")).toBe(true);
    expect(statuses.has("completed")).toBe(true);
    expect(statuses.has("validation_failed")).toBe(true);
    expect(statuses.has("failed")).toBe(true);
    expect(statuses.has("cancelled")).toBe(true);
  });

  it.each(fixtures.map((f) => [f.id, f] as const))(
    "%s: valid_rows = total_rows - invalid_rows whenever counters are populated",
    (_id, fixture) => {
      if (fixture.totalRows === null) {
        expect(fixture.validRows).toBeNull();
        expect(fixture.invalidRows).toBeNull();
        expect(fixture.warningRows).toBeNull();
        return;
      }
      expect(fixture.validRows).toBe(fixture.totalRows - (fixture.invalidRows as number));
    }
  );

  it.each(fixtures.map((f) => [f.id, f] as const))(
    "%s: invalidRows/warningRows match distinct-row counts derived from findings",
    (_id, fixture) => {
      if (fixture.totalRows === null) return;
      expect(fixture.invalidRows).toBe(countDistinctRowsBySeverity(fixture.findings, "error"));
      expect(fixture.warningRows).toBe(countDistinctRowsBySeverity(fixture.findings, "warning"));
    }
  );

  it.each(fixtures.filter((f) => STATUSES_REQUIRING_ZERO_INVALID_ROWS.has(f.status)).map((f) => [f.id, f] as const))(
    "%s: dry-run/execute/completed statuses never carry invalid rows or blocking ERROR findings",
    (_id, fixture) => {
      expect(fixture.invalidRows).toBe(0);
      expect(fixture.findings.some((finding) => finding.severity === "error")).toBe(false);
    }
  );

  it("every dry_run_completed fixture has invalidRows === 0 (confirm-gate is only reachable from VALIDATED)", () => {
    const dryRunCompleted = fixtures.filter((f) => f.status === "dry_run_completed");
    expect(dryRunCompleted.length).toBeGreaterThan(0);
    for (const fixture of dryRunCompleted) {
      expect(fixture.invalidRows).toBe(0);
    }
  });

  it("validation_failed fixtures either have fully-null counters (structural failure) or counters consistent with their findings", () => {
    const validationFailed = fixtures.filter((f) => f.status === "validation_failed");
    expect(validationFailed.length).toBeGreaterThan(0);
    for (const fixture of validationFailed) {
      if (fixture.totalRows === null) {
        expect(fixture.validRows).toBeNull();
        continue;
      }
      expect(fixture.validRows).toBe(fixture.totalRows - (fixture.invalidRows as number));
      expect(fixture.invalidRows).toBe(countDistinctRowsBySeverity(fixture.findings, "error"));
    }
  });

  it("warnings never reduce validRows (a row with only a WARNING finding is still valid)", () => {
    for (const fixture of fixtures) {
      if (fixture.totalRows === null || (fixture.warningRows ?? 0) === 0) continue;
      // If warnings incorrectly subtracted from valid rows, validRows would
      // be less than totalRows - invalidRows; the invariant test above
      // already pins the exact equality, this asserts the specific failure
      // mode the review flagged doesn't reappear.
      expect(fixture.validRows).toBe((fixture.totalRows as number) - (fixture.invalidRows as number));
    }
  });

  it.each(fixtures.filter((f) => TERMINAL_STATUSES.has(f.status)).map((f) => [f.id, f] as const))(
    "%s: terminal sessions always set terminalAt and never claim a false import outcome",
    (_id, fixture) => {
      expect(fixture.resultSummary).not.toBeNull();
      expect(fixture.resultSummary?.terminalAt).not.toBeNull();
      expect(fixture.resultSummary?.status).toBe(fixture.status);
      if (fixture.status === "completed") {
        expect(fixture.resultSummary?.importedRows).not.toBeNull();
      } else {
        // failed / cancelled: neither ever executes successfully.
        expect(fixture.resultSummary?.importedRows).toBeNull();
      }
    }
  );

  it("non-terminal fixtures never have a resultSummary", () => {
    for (const fixture of fixtures.filter((f) => !TERMINAL_STATUSES.has(f.status))) {
      expect(fixture.resultSummary).toBeNull();
    }
  });

  it("createMockImportSession's factory output never carries a blocking ERROR finding (dry_run_completed is only reachable post-VALIDATED)", () => {
    const created = createMockImportSession({
      importCategory: "equipment_master",
      file: { name: "smoke-test.xlsx", sizeBytes: 1, type: "" },
      requestedByDisplayName: "ผู้ทดสอบ",
    });
    expect(created.status).toBe("dry_run_completed");
    expect(created.invalidRows).toBe(0);
    expect(created.validRows).toBe(created.totalRows);
    expect(created.findings.some((f) => f.severity === "error")).toBe(false);
  });

  it("assertImportSessionInvariants rejects contradictory states, proving the guard actually guards", () => {
    // Needs a fixture with a nonzero warningRows so subtracting it too
    // actually produces a different (wrong) number than the correct one.
    const base = fixtures.find((f) => f.status === "completed" && (f.warningRows ?? 0) > 0);
    expect(base).toBeDefined();
    const validSession = base!;

    // valid_rows computed by subtracting warning_rows too, the exact bug
    // this review flagged.
    expect(() =>
      assertImportSessionInvariants({
        ...validSession,
        validRows: (validSession.totalRows as number) - (validSession.invalidRows as number) - (validSession.warningRows as number),
      })
    ).toThrow(/validRows/);

    // a blocking ERROR finding smuggled into a dry_run_completed snapshot.
    expect(() =>
      assertImportSessionInvariants({
        ...validSession,
        status: "dry_run_completed",
        invalidRows: 1,
        validRows: (validSession.totalRows as number) - 1,
        warningRows: 0,
        findings: [
          { id: "bad", rowNumber: 1, field: null, errorCode: "X", message: "x", severity: "error" },
        ],
      })
    ).toThrow(/dry_run_completed/);

    // a cancelled session claiming a nonzero "0 rows imported" outcome.
    expect(() =>
      assertImportSessionInvariants({
        ...validSession,
        status: "cancelled",
        resultSummary: { status: "cancelled", importedRows: 0, terminalAt: "2026-01-01T00:00:00Z", sessionId: validSession.id },
      })
    ).toThrow(/cancelled/);

    // a terminal session with no terminalAt at all.
    expect(() =>
      assertImportSessionInvariants({
        ...validSession,
        resultSummary: { ...(validSession.resultSummary as NonNullable<typeof validSession.resultSummary>), terminalAt: null },
      })
    ).toThrow(/terminalAt/);
  });
});
