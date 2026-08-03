import type {
  ImportCategory,
  ImportSessionDetail,
  ImportSessionStatus,
  SelectedFilePreview,
} from "@/types/legacyImport";

// PR19B skeleton only -- see types/legacyImport.ts's file-level note. Every
// value below is representative/invented sample data for UI review. None of
// it comes from, or is derived from, real hospital data.

let sessionCounter = 0;

function nextId(prefix: string): string {
  sessionCounter += 1;
  return `${prefix}-${sessionCounter}`;
}

const AWAITING_CONFIRMATION_FIXTURE: ImportSessionDetail = {
  id: "demo-awaiting-confirmation",
  importCategory: "receive_history",
  filename: "receive-history-2026-Q2.xlsx",
  status: "awaiting_confirmation",
  requestedByDisplayName: "สมชาย ใจดี",
  createdAt: "2026-07-20T03:00:00Z",
  totalRows: 480,
  importedCount: null,
  skippedCount: null,
  failedCount: null,
  requestedFileSizeBytes: 812_400,
  validationSummary: {
    totalRows: 480,
    validRows: 430,
    warningRows: 32,
    invalidRows: 12,
    duplicateRows: 6,
    byCategory: [
      { categoryLabelTh: "รูปแบบวันที่ไม่ถูกต้อง", count: 5 },
      { categoryLabelTh: "ไม่พบหอผู้ป่วยที่ตรงกัน", count: 4 },
      { categoryLabelTh: "ไม่พบรหัส BCM ที่ตรงกัน", count: 3 },
    ],
  },
  issues: [
    {
      rowNumber: 12,
      field: "วันที่รับคืน",
      submittedValue: "31/13/2026",
      issueCode: "INVALID_DATE",
      explanationTh: "รูปแบบวันที่ไม่ถูกต้อง ควรเป็น วัน/เดือน/ปี",
      severity: "error",
    },
    {
      rowNumber: 45,
      field: "หอผู้ป่วย",
      submittedValue: "ICU-เก่า",
      issueCode: "WARD_NOT_MATCHED",
      explanationTh: "ไม่พบหอผู้ป่วยที่ตรงกันในระบบปัจจุบัน จะต้องจับคู่ก่อนนำเข้า",
      severity: "warning",
    },
    {
      rowNumber: 88,
      field: "รหัส BCM",
      submittedValue: "BCM-000000",
      issueCode: "BCM_NOT_FOUND",
      explanationTh: "ไม่พบรหัส BCM นี้ในข้อมูลหลักเครื่องมือปัจจุบัน",
      severity: "error",
    },
    {
      rowNumber: 101,
      field: "แถวข้อมูล",
      submittedValue: "แถว 101 กับแถว 205",
      issueCode: "DUPLICATE_ROW",
      explanationTh: "ข้อมูลซ้ำกับอีกแถวหนึ่งในไฟล์เดียวกัน",
      severity: "warning",
    },
  ],
  dryRunSummary: {
    wouldCreateCount: 430,
    wouldSkipCount: 18,
    duplicateCount: 6,
    validationFailureCount: 12,
    warningCount: 32,
  },
  resultSummary: null,
};

const COMPLETED_FIXTURE: ImportSessionDetail = {
  id: "demo-completed",
  importCategory: "equipment_master",
  filename: "equipment-master-2026-06.xlsx",
  status: "completed",
  requestedByDisplayName: "สมหญิง รักงาน",
  createdAt: "2026-06-15T02:30:00Z",
  totalRows: 210,
  importedCount: 205,
  skippedCount: 5,
  failedCount: 0,
  requestedFileSizeBytes: 340_112,
  validationSummary: {
    totalRows: 210,
    validRows: 205,
    warningRows: 5,
    invalidRows: 0,
    duplicateRows: 0,
    byCategory: [{ categoryLabelTh: "พบรหัส BCM ซ้ำในระบบ (ข้าม)", count: 5 }],
  },
  issues: [
    {
      rowNumber: 60,
      field: "รหัส BCM",
      submittedValue: "BCM-100234",
      issueCode: "ALREADY_EXISTS",
      explanationTh: "มีรายการนี้อยู่แล้วในระบบ ระบบข้ามแถวนี้",
      severity: "warning",
    },
  ],
  dryRunSummary: {
    wouldCreateCount: 205,
    wouldSkipCount: 5,
    duplicateCount: 0,
    validationFailureCount: 0,
    warningCount: 5,
  },
  resultSummary: {
    status: "completed",
    importedCount: 205,
    skippedCount: 5,
    failedCount: 0,
    completedAt: "2026-06-15T02:35:00Z",
    sessionReference: "demo-completed",
  },
};

const COMPLETED_WITH_WARNINGS_FIXTURE: ImportSessionDetail = {
  ...COMPLETED_FIXTURE,
  id: "demo-completed-warnings",
  importCategory: "issue_history",
  filename: "issue-history-2026-05.xlsx",
  status: "completed_with_warnings",
  createdAt: "2026-05-10T04:00:00Z",
  resultSummary: {
    status: "completed_with_warnings",
    importedCount: 190,
    skippedCount: 20,
    failedCount: 0,
    completedAt: "2026-05-10T04:06:00Z",
    sessionReference: "demo-completed-warnings",
  },
  importedCount: 190,
  skippedCount: 20,
  failedCount: 0,
};

const FAILED_FIXTURE: ImportSessionDetail = {
  id: "demo-failed",
  importCategory: "receive_history",
  filename: "receive-history-corrupt.xlsx",
  status: "failed",
  requestedByDisplayName: "สมชาย ใจดี",
  createdAt: "2026-04-02T01:00:00Z",
  totalRows: null,
  importedCount: 0,
  skippedCount: 0,
  failedCount: 0,
  requestedFileSizeBytes: 15_200,
  validationSummary: null,
  issues: [
    {
      rowNumber: 1,
      field: "ไฟล์",
      submittedValue: "receive-history-corrupt.xlsx",
      issueCode: "FILE_UNREADABLE",
      explanationTh: "ไม่สามารถอ่านไฟล์นี้ได้ กรุณาตรวจสอบรูปแบบไฟล์แล้วลองใหม่",
      severity: "error",
    },
  ],
  dryRunSummary: null,
  resultSummary: {
    status: "failed",
    importedCount: 0,
    skippedCount: 0,
    failedCount: 0,
    completedAt: "2026-04-02T01:01:00Z",
    sessionReference: "demo-failed",
  },
};

const CANCELLED_FIXTURE: ImportSessionDetail = {
  id: "demo-cancelled",
  importCategory: "equipment_master",
  filename: "equipment-master-draft.xlsx",
  status: "cancelled",
  requestedByDisplayName: "สมหญิง รักงาน",
  createdAt: "2026-03-01T06:00:00Z",
  totalRows: 60,
  importedCount: 0,
  skippedCount: 0,
  failedCount: 0,
  requestedFileSizeBytes: 98_000,
  validationSummary: {
    totalRows: 60,
    validRows: 55,
    warningRows: 5,
    invalidRows: 0,
    duplicateRows: 0,
    byCategory: [],
  },
  issues: [],
  dryRunSummary: {
    wouldCreateCount: 55,
    wouldSkipCount: 5,
    duplicateCount: 0,
    validationFailureCount: 0,
    warningCount: 5,
  },
  resultSummary: {
    status: "cancelled",
    importedCount: 0,
    skippedCount: 0,
    failedCount: 0,
    completedAt: null,
    sessionReference: "demo-cancelled",
  },
};

// Default representative seed set for the session list -- covers every
// terminal/non-terminal status this skeleton renders (see "Error and state
// coverage" in the PR19B task brief), used both by the real dev-mode
// MockImportClient and directly by tests needing a full seed set.
export const legacyImportSkeletonFixtures: ImportSessionDetail[] = [
  AWAITING_CONFIRMATION_FIXTURE,
  COMPLETED_FIXTURE,
  COMPLETED_WITH_WARNINGS_FIXTURE,
  FAILED_FIXTURE,
  CANCELLED_FIXTURE,
];

const CATEGORY_DEMO_ROW_COUNTS: Record<ImportCategory, number> = {
  equipment_master: 150,
  receive_history: 480,
  issue_history: 512,
};

// Builds a new, deterministic-shape preview session for the create-session
// wizard's "ตรวจสอบข้อมูล" step. Counts are fixed sample numbers keyed only
// by import category -- never computed from the caller's actual selected
// file (task scope: "Do not calculate these counts from the selected
// file").
export function createMockImportSession(input: {
  importCategory: ImportCategory;
  file: SelectedFilePreview;
  requestedByDisplayName: string;
}): ImportSessionDetail {
  const totalRows = CATEGORY_DEMO_ROW_COUNTS[input.importCategory];
  const invalidRows = Math.round(totalRows * 0.03);
  const warningRows = Math.round(totalRows * 0.07);
  const duplicateRows = Math.round(totalRows * 0.02);
  const validRows = totalRows - invalidRows - duplicateRows;
  const status: ImportSessionStatus = "awaiting_confirmation";

  return {
    id: nextId("preview"),
    importCategory: input.importCategory,
    filename: input.file.name,
    status,
    requestedByDisplayName: input.requestedByDisplayName,
    createdAt: new Date().toISOString(),
    totalRows,
    importedCount: null,
    skippedCount: null,
    failedCount: null,
    requestedFileSizeBytes: input.file.sizeBytes,
    validationSummary: {
      totalRows,
      validRows,
      warningRows,
      invalidRows,
      duplicateRows,
      byCategory: [
        { categoryLabelTh: "รูปแบบข้อมูลไม่ถูกต้อง (ตัวอย่าง)", count: invalidRows },
        { categoryLabelTh: "ไม่พบข้อมูลอ้างอิงที่ตรงกัน (ตัวอย่าง)", count: warningRows },
      ],
    },
    issues: [
      {
        rowNumber: 7,
        field: "ตัวอย่างคอลัมน์",
        submittedValue: "ตัวอย่างค่าที่ส่งมา",
        issueCode: "SAMPLE_ISSUE",
        explanationTh: "ตัวอย่างคำอธิบายปัญหา สำหรับต้นแบบหน้าจอเท่านั้น",
        severity: "error",
      },
      {
        rowNumber: 19,
        field: "ตัวอย่างคอลัมน์",
        submittedValue: "ตัวอย่างค่าที่ส่งมา",
        issueCode: "SAMPLE_WARNING",
        explanationTh: "ตัวอย่างคำเตือน สำหรับต้นแบบหน้าจอเท่านั้น",
        severity: "warning",
      },
    ],
    dryRunSummary: {
      wouldCreateCount: validRows,
      wouldSkipCount: duplicateRows,
      duplicateCount: duplicateRows,
      validationFailureCount: invalidRows,
      warningCount: warningRows,
    },
    resultSummary: null,
  };
}
