import { assertImportSessionInvariants, countDistinctRowsBySeverity } from "@/utils/legacyImportInvariants";
import type {
  ImportCategory,
  ImportFinding,
  ImportFindingCategoryCount,
  ImportSessionDetail,
  SelectedFilePreview,
} from "@/types/legacyImport";

// PR19B skeleton only -- see types/legacyImport.ts's file-level note. Every
// value below is representative/invented sample data for UI review. None of
// it comes from, or is derived from, real hospital data. Field shapes match
// the merged PR19A backend contract (ImportSessionOut/ValidationFindingOut);
// see types/legacyImport.ts for the field-by-field mapping.
//
// Every fixture below is built with `findings` as the single source of
// truth for invalid/warning row counts (via `countDistinctRowsBySeverity`)
// and `buildFindingsByCategory` -- counters are never hand-typed
// separately from the findings that back them, and `assertImportSessionInvariants`
// (called at module load for every static fixture, and again inside
// `createMockImportSession` for the dynamic one) makes it structurally
// impossible for a fixture in this file to represent a state the real
// backend contract could never produce (docs/design/
// PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md §5/§12/§13/§18).

let sessionCounter = 0;

function nextId(prefix: string): string {
  sessionCounter += 1;
  return `${prefix}-${sessionCounter}`;
}

// Presentational-only label per errorCode, used solely to build each
// fixture's `findingsByCategory` from its own `findings` -- not a real
// backend aggregate (no such endpoint exists in this foundation).
const FINDING_CATEGORY_LABELS: Record<string, string> = {
  INVALID_DATE: "รูปแบบวันที่ไม่ถูกต้อง",
  WARD_NOT_MATCHED: "ไม่พบหอผู้ป่วยที่ตรงกัน",
  BCM_NOT_FOUND: "ไม่พบรหัส BCM ที่ตรงกัน",
  DUPLICATE_ROW: "ข้อมูลซ้ำกับแถวอื่นในไฟล์เดียวกัน",
  ALREADY_EXISTS: "มีรายการนี้อยู่แล้วในระบบ",
  FILE_UNREADABLE: "ไม่สามารถอ่านไฟล์ได้",
  SAMPLE_WARNING: "ตัวอย่างคำเตือน",
};

// Derived strictly from `findings` -- see this file's top-level note. Two
// fixtures never need to keep a separately-typed category list in sync
// with their own findings array by hand.
function buildFindingsByCategory(findings: ImportFinding[]): ImportFindingCategoryCount[] {
  const counts = new Map<string, number>();
  for (const finding of findings) {
    const label = FINDING_CATEGORY_LABELS[finding.errorCode] ?? finding.errorCode;
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return Array.from(counts, ([categoryLabelTh, count]) => ({ categoryLabelTh, count }));
}

// Builds a fully-consistent `ImportSessionDetail` from a small set of
// authored inputs (id/category/status/findings/etc.), deriving every
// count from `findings` rather than accepting hand-typed numbers that
// could drift from it. Throws via `assertImportSessionInvariants` if the
// combination is one the real backend could never produce.
function buildDetail(input: {
  id: string;
  datasetType: ImportCategory;
  filename: string;
  status: ImportSessionDetail["status"];
  createdByUserId: string;
  requestedByDisplayName: string;
  createdAt: string;
  totalRows: number | null;
  requestedFileSizeBytes: number;
  findings: ImportFinding[];
  resultSummary: ImportSessionDetail["resultSummary"];
}): ImportSessionDetail {
  const hasCounts = input.totalRows !== null;
  const invalidRows = hasCounts ? countDistinctRowsBySeverity(input.findings, "error") : null;
  const warningRows = hasCounts ? countDistinctRowsBySeverity(input.findings, "warning") : null;
  const validRows = hasCounts ? (input.totalRows as number) - (invalidRows as number) : null;

  const detail: ImportSessionDetail = {
    id: input.id,
    datasetType: input.datasetType,
    filename: input.filename,
    status: input.status,
    createdByUserId: input.createdByUserId,
    requestedByDisplayName: input.requestedByDisplayName,
    createdAt: input.createdAt,
    totalRows: input.totalRows,
    validRows,
    invalidRows,
    warningRows,
    importedRows: input.resultSummary?.importedRows ?? null,
    requestedFileSizeBytes: input.requestedFileSizeBytes,
    validationCounts: hasCounts
      ? { totalRows: input.totalRows as number, validRows: validRows as number, warningRows: warningRows as number, invalidRows: invalidRows as number }
      : null,
    findingsByCategory: buildFindingsByCategory(input.findings),
    findings: input.findings,
    resultSummary: input.resultSummary,
  };

  assertImportSessionInvariants(detail);
  return detail;
}

// Status = dry_run_completed: the real confirm-gate state (design §5) --
// not an invented "awaiting_confirmation" status. dry-run is reachable
// only from VALIDATED, so this snapshot's findings are warning-only (an
// ERROR finding here would mean the session could never have reached
// VALIDATED in the first place, design §12/§13) -- enforced structurally
// by `buildDetail`/`assertImportSessionInvariants`, not just by
// convention.
const DRY_RUN_COMPLETED_FIXTURE: ImportSessionDetail = buildDetail({
  id: "demo-dry-run-completed",
  datasetType: "receive_history",
  filename: "receive-history-2026-Q2.xlsx",
  status: "dry_run_completed",
  createdByUserId: "demo-user-1",
  requestedByDisplayName: "สมชาย ใจดี",
  createdAt: "2026-07-20T03:00:00Z",
  totalRows: 480,
  requestedFileSizeBytes: 812_400,
  findings: [
    {
      id: "demo-finding-1",
      rowNumber: 45,
      field: "หอผู้ป่วย",
      errorCode: "WARD_NOT_MATCHED",
      message: "ไม่พบหอผู้ป่วยที่ตรงกันในระบบปัจจุบัน (ค่าที่ส่งมา: ICU-เก่า) จะต้องจับคู่ก่อนนำเข้า -- ไม่ปิดกั้นการทดลองนำเข้า",
      severity: "warning",
    },
    {
      id: "demo-finding-2",
      rowNumber: 101,
      field: "แถวข้อมูล",
      errorCode: "DUPLICATE_ROW",
      message: "ข้อมูลซ้ำกับแถว 205 ในไฟล์เดียวกัน -- ไม่ปิดกั้นการทดลองนำเข้า",
      severity: "warning",
    },
  ],
  resultSummary: null,
});

// Status = completed, zero warnings.
const COMPLETED_FIXTURE: ImportSessionDetail = buildDetail({
  id: "demo-completed",
  datasetType: "equipment_master",
  filename: "equipment-master-2026-06.xlsx",
  status: "completed",
  createdByUserId: "demo-user-2",
  requestedByDisplayName: "สมหญิง รักงาน",
  createdAt: "2026-06-15T02:30:00Z",
  totalRows: 210,
  requestedFileSizeBytes: 340_112,
  findings: [],
  resultSummary: {
    status: "completed",
    importedRows: 210,
    terminalAt: "2026-06-15T02:35:00Z",
    sessionId: "demo-completed",
  },
});

// Status = completed, with warning-severity findings -- demonstrates that a
// WARNING never blocks progress (design §13): the session still reaches
// `completed` with every valid row imported, including the one carrying a
// non-blocking warning.
const COMPLETED_WITH_WARNINGS_FIXTURE: ImportSessionDetail = buildDetail({
  id: "demo-completed-warnings",
  datasetType: "issue_history",
  filename: "issue-history-2026-05.xlsx",
  status: "completed",
  createdByUserId: "demo-user-1",
  requestedByDisplayName: "สมชาย ใจดี",
  createdAt: "2026-05-10T04:00:00Z",
  totalRows: 210,
  requestedFileSizeBytes: 298_500,
  findings: [
    {
      id: "demo-finding-3",
      rowNumber: 60,
      field: "รหัส BCM",
      errorCode: "ALREADY_EXISTS",
      message: "มีรายการนี้อยู่แล้วในระบบ (ค่าที่ส่งมา: BCM-100234) -- คำเตือนนี้ไม่ปิดกั้นการนำเข้า",
      severity: "warning",
    },
  ],
  resultSummary: {
    status: "completed",
    importedRows: 210,
    terminalAt: "2026-05-10T04:06:00Z",
    sessionId: "demo-completed-warnings",
  },
});

// Status = validation_failed, structural failure flavor: a validation
// attempt that crashed/was recovered before producing any row-level
// counts at all (design §9.4.2's "cleanly-recorded failure" path) --
// total/valid/invalid/warning rows legitimately stay null here rather
// than being filled in with invented numbers.
const VALIDATION_FAILED_FIXTURE: ImportSessionDetail = buildDetail({
  id: "demo-validation-failed",
  datasetType: "receive_history",
  filename: "receive-history-corrupt.xlsx",
  status: "validation_failed",
  createdByUserId: "demo-user-1",
  requestedByDisplayName: "สมชาย ใจดี",
  createdAt: "2026-04-02T01:00:00Z",
  totalRows: null,
  requestedFileSizeBytes: 15_200,
  findings: [
    {
      id: "demo-finding-4",
      rowNumber: null,
      field: null,
      errorCode: "FILE_UNREADABLE",
      message: "ไม่สามารถอ่านไฟล์นี้ได้ กรุณาตรวจสอบรูปแบบไฟล์แล้วลองใหม่",
      severity: "error",
    },
  ],
  resultSummary: null,
});

// Status = validation_failed, row-level flavor: a validation attempt that
// ran to completion and found blocking errors on some rows (design §13 --
// "a completed pass that finds blocking errors is still success for
// job-completion purposes"). Distinct from the structural-failure fixture
// above -- here total/valid/invalid/warning rows are all real, and
// invalidRows/warningRows are derived from (and must match) `findings`.
const VALIDATION_FAILED_WITH_FINDINGS_FIXTURE: ImportSessionDetail = buildDetail({
  id: "demo-validation-failed-rows",
  datasetType: "receive_history",
  filename: "receive-history-2026-Q1.xlsx",
  status: "validation_failed",
  createdByUserId: "demo-user-1",
  requestedByDisplayName: "สมชาย ใจดี",
  createdAt: "2026-04-10T01:00:00Z",
  totalRows: 480,
  requestedFileSizeBytes: 795_000,
  findings: [
    {
      id: "demo-finding-5",
      rowNumber: 12,
      field: "วันที่รับคืน",
      errorCode: "INVALID_DATE",
      message: "รูปแบบวันที่ไม่ถูกต้อง ควรเป็น วัน/เดือน/ปี (ค่าที่ส่งมา: 31/13/2026)",
      severity: "error",
    },
    {
      id: "demo-finding-6",
      rowNumber: 88,
      field: "รหัส BCM",
      errorCode: "BCM_NOT_FOUND",
      message: "ไม่พบรหัส BCM นี้ในข้อมูลหลักเครื่องมือปัจจุบัน (ค่าที่ส่งมา: BCM-000000)",
      severity: "error",
    },
    {
      id: "demo-finding-7",
      rowNumber: 45,
      field: "หอผู้ป่วย",
      errorCode: "WARD_NOT_MATCHED",
      message: "ไม่พบหอผู้ป่วยที่ตรงกันในระบบปัจจุบัน (ค่าที่ส่งมา: ICU-เก่า)",
      severity: "warning",
    },
  ],
  resultSummary: null,
});

// Status = failed (terminal): execute() itself raised unexpectedly after a
// successful dry-run (design §17, IMPORT_EXECUTION_FAILED). Every domain
// write from that attempt is rolled back (design §19), so nothing was
// ever actually imported -- importedRows is null, never a coerced 0.
const FAILED_FIXTURE: ImportSessionDetail = buildDetail({
  id: "demo-execute-failed",
  datasetType: "equipment_master",
  filename: "equipment-master-2026-02.xlsx",
  status: "failed",
  createdByUserId: "demo-user-2",
  requestedByDisplayName: "สมหญิง รักงาน",
  createdAt: "2026-02-18T05:00:00Z",
  totalRows: 300,
  requestedFileSizeBytes: 420_000,
  findings: [
    {
      id: "demo-finding-8",
      rowNumber: 22,
      field: "รหัส BCM",
      errorCode: "WARD_NOT_MATCHED",
      message: "ไม่พบหอผู้ป่วยที่ตรงกันในระบบปัจจุบัน -- ไม่ปิดกั้นการนำเข้า",
      severity: "warning",
    },
  ],
  resultSummary: {
    status: "failed",
    importedRows: null,
    terminalAt: "2026-02-18T05:12:00Z",
    sessionId: "demo-execute-failed",
  },
});

// Status = cancelled (terminal): cancelled from a DRY_RUN_COMPLETED state
// (design §5's transition table) -- reachable with invalidRows still 0.
// Cancel is only ever reachable *before* execute, so importedRows is null,
// never a coerced 0 (unlike the pre-reconciliation version of this
// fixture, which incorrectly claimed both "0 rows imported" and a null
// terminalAt -- terminal_at is in fact always set for CANCELLED, design §18).
const CANCELLED_FIXTURE: ImportSessionDetail = buildDetail({
  id: "demo-cancelled",
  datasetType: "equipment_master",
  filename: "equipment-master-draft.xlsx",
  status: "cancelled",
  createdByUserId: "demo-user-2",
  requestedByDisplayName: "สมหญิง รักงาน",
  createdAt: "2026-03-01T06:00:00Z",
  totalRows: 60,
  requestedFileSizeBytes: 98_000,
  findings: [
    {
      id: "demo-finding-9",
      rowNumber: 10,
      field: "หอผู้ป่วย",
      errorCode: "WARD_NOT_MATCHED",
      message: "ไม่พบหอผู้ป่วยที่ตรงกันในระบบปัจจุบัน -- ไม่ปิดกั้นการทดลองนำเข้า",
      severity: "warning",
    },
  ],
  resultSummary: {
    status: "cancelled",
    importedRows: null,
    terminalAt: "2026-03-01T06:05:00Z",
    sessionId: "demo-cancelled",
  },
});

// Default representative seed set for the session list -- covers dry-run
// (confirm-gate), completed, completed-with-warnings, both
// validation-failed flavors, execute failure, and cancellation, used both
// by the real dev-mode MockImportClient and directly by tests needing a
// full seed set.
export const legacyImportSkeletonFixtures: ImportSessionDetail[] = [
  DRY_RUN_COMPLETED_FIXTURE,
  COMPLETED_FIXTURE,
  COMPLETED_WITH_WARNINGS_FIXTURE,
  VALIDATION_FAILED_FIXTURE,
  VALIDATION_FAILED_WITH_FINDINGS_FIXTURE,
  FAILED_FIXTURE,
  CANCELLED_FIXTURE,
];

const CATEGORY_DEMO_ROW_COUNTS: Record<ImportCategory, number> = {
  equipment_master: 150,
  receive_history: 480,
  issue_history: 512,
};

// Builds a new, deterministic-shape preview session for the create-session
// wizard's "ตรวจสอบข้อมูล" step. Row count is a fixed sample number keyed
// only by import category -- never computed from the caller's actual
// selected file (task scope: "Do not calculate these counts from the
// selected file"). Lands directly on `dry_run_completed`, matching the
// real confirm-gate status -- so, like every other dry_run_completed
// fixture above, its findings must be warning-only (enforced by
// `buildDetail`).
export function createMockImportSession(input: {
  importCategory: ImportCategory;
  file: SelectedFilePreview;
  requestedByDisplayName: string;
}): ImportSessionDetail {
  const totalRows = CATEGORY_DEMO_ROW_COUNTS[input.importCategory];
  const id = nextId("preview");

  return buildDetail({
    id,
    datasetType: input.importCategory,
    filename: input.file.name,
    status: "dry_run_completed",
    createdByUserId: "demo-user-1",
    requestedByDisplayName: input.requestedByDisplayName,
    createdAt: new Date().toISOString(),
    totalRows,
    requestedFileSizeBytes: input.file.sizeBytes,
    findings: [
      {
        id: nextId("finding"),
        rowNumber: 7,
        field: "ตัวอย่างคอลัมน์",
        errorCode: "SAMPLE_WARNING",
        message: "ตัวอย่างคำเตือน สำหรับต้นแบบหน้าจอเท่านั้น -- ไม่ปิดกั้นการทดลองนำเข้า",
        severity: "warning",
      },
    ],
    resultSummary: null,
  });
}
