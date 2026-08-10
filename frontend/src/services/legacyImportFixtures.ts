import type {
  ImportCategory,
  ImportSessionDetail,
  ImportSessionStatus,
  SelectedFilePreview,
} from "@/types/legacyImport";

// PR19B skeleton only -- see types/legacyImport.ts's file-level note. Every
// value below is representative/invented sample data for UI review. None of
// it comes from, or is derived from, real hospital data. Field shapes match
// the merged PR19A backend contract (ImportSessionOut/ValidationFindingOut);
// see types/legacyImport.ts for the field-by-field mapping.

let sessionCounter = 0;

function nextId(prefix: string): string {
  sessionCounter += 1;
  return `${prefix}-${sessionCounter}`;
}

// Status = dry_run_completed: the real confirm-gate state (design §5) --
// not an invented "awaiting_confirmation" status. The detail page shows
// the disabled confirm panel whenever status is exactly this value.
const DRY_RUN_COMPLETED_FIXTURE: ImportSessionDetail = {
  id: "demo-dry-run-completed",
  datasetType: "receive_history",
  filename: "receive-history-2026-Q2.xlsx",
  status: "dry_run_completed",
  createdByUserId: "demo-user-1",
  requestedByDisplayName: "สมชาย ใจดี",
  createdAt: "2026-07-20T03:00:00Z",
  totalRows: 480,
  validRows: 430,
  invalidRows: 12,
  warningRows: 32,
  importedRows: null,
  requestedFileSizeBytes: 812_400,
  validationCounts: { totalRows: 480, validRows: 430, warningRows: 32, invalidRows: 12 },
  findingsByCategory: [
    { categoryLabelTh: "รูปแบบวันที่ไม่ถูกต้อง", count: 5 },
    { categoryLabelTh: "ไม่พบหอผู้ป่วยที่ตรงกัน", count: 4 },
    { categoryLabelTh: "ไม่พบรหัส BCM ที่ตรงกัน", count: 3 },
  ],
  findings: [
    {
      id: "demo-finding-1",
      rowNumber: 12,
      field: "วันที่รับคืน",
      errorCode: "INVALID_DATE",
      message: "รูปแบบวันที่ไม่ถูกต้อง ควรเป็น วัน/เดือน/ปี (ค่าที่ส่งมา: 31/13/2026)",
      severity: "error",
    },
    {
      id: "demo-finding-2",
      rowNumber: 45,
      field: "หอผู้ป่วย",
      errorCode: "WARD_NOT_MATCHED",
      message: "ไม่พบหอผู้ป่วยที่ตรงกันในระบบปัจจุบัน (ค่าที่ส่งมา: ICU-เก่า) จะต้องจับคู่ก่อนนำเข้า",
      severity: "warning",
    },
    {
      id: "demo-finding-3",
      rowNumber: 88,
      field: "รหัส BCM",
      errorCode: "BCM_NOT_FOUND",
      message: "ไม่พบรหัส BCM นี้ในข้อมูลหลักเครื่องมือปัจจุบัน (ค่าที่ส่งมา: BCM-000000)",
      severity: "error",
    },
    {
      id: "demo-finding-4",
      rowNumber: 101,
      field: "แถวข้อมูล",
      errorCode: "DUPLICATE_ROW",
      message: "ข้อมูลซ้ำกับแถว 205 ในไฟล์เดียวกัน",
      severity: "warning",
    },
  ],
  resultSummary: null,
};

// Status = completed, zero warnings.
const COMPLETED_FIXTURE: ImportSessionDetail = {
  id: "demo-completed",
  datasetType: "equipment_master",
  filename: "equipment-master-2026-06.xlsx",
  status: "completed",
  createdByUserId: "demo-user-2",
  requestedByDisplayName: "สมหญิง รักงาน",
  createdAt: "2026-06-15T02:30:00Z",
  totalRows: 210,
  validRows: 210,
  invalidRows: 0,
  warningRows: 0,
  importedRows: 210,
  requestedFileSizeBytes: 340_112,
  validationCounts: { totalRows: 210, validRows: 210, warningRows: 0, invalidRows: 0 },
  findingsByCategory: [],
  findings: [],
  resultSummary: {
    status: "completed",
    importedRows: 210,
    terminalAt: "2026-06-15T02:35:00Z",
    sessionId: "demo-completed",
  },
};

// Status = completed, with warning-severity findings -- demonstrates that a
// WARNING never blocks progress (design §24 rule 10): the session still
// reaches `completed`, it just carries non-blocking warning findings.
const COMPLETED_WITH_WARNINGS_FIXTURE: ImportSessionDetail = {
  id: "demo-completed-warnings",
  datasetType: "issue_history",
  filename: "issue-history-2026-05.xlsx",
  status: "completed",
  createdByUserId: "demo-user-1",
  requestedByDisplayName: "สมชาย ใจดี",
  createdAt: "2026-05-10T04:00:00Z",
  totalRows: 210,
  validRows: 205,
  invalidRows: 0,
  warningRows: 5,
  importedRows: 205,
  requestedFileSizeBytes: 298_500,
  validationCounts: { totalRows: 210, validRows: 205, warningRows: 5, invalidRows: 0 },
  findingsByCategory: [{ categoryLabelTh: "พบรหัส BCM ซ้ำในระบบ (ข้าม)", count: 5 }],
  findings: [
    {
      id: "demo-finding-5",
      rowNumber: 60,
      field: "รหัส BCM",
      errorCode: "ALREADY_EXISTS",
      message: "มีรายการนี้อยู่แล้วในระบบ (ค่าที่ส่งมา: BCM-100234) ระบบข้ามแถวนี้ -- ไม่ปิดกั้นการนำเข้าส่วนที่เหลือ",
      severity: "warning",
    },
  ],
  resultSummary: {
    status: "completed",
    importedRows: 205,
    terminalAt: "2026-05-10T04:06:00Z",
    sessionId: "demo-completed-warnings",
  },
};

// Status = validation_failed -- a non-terminal status (design §5): the
// session can be re-validated, unlike the terminal FAILED status (which
// represents a genuine execute()-time runtime failure).
const VALIDATION_FAILED_FIXTURE: ImportSessionDetail = {
  id: "demo-validation-failed",
  datasetType: "receive_history",
  filename: "receive-history-corrupt.xlsx",
  status: "validation_failed",
  createdByUserId: "demo-user-1",
  requestedByDisplayName: "สมชาย ใจดี",
  createdAt: "2026-04-02T01:00:00Z",
  totalRows: null,
  validRows: null,
  invalidRows: null,
  warningRows: null,
  importedRows: null,
  requestedFileSizeBytes: 15_200,
  validationCounts: null,
  findingsByCategory: [],
  findings: [
    {
      id: "demo-finding-6",
      rowNumber: null,
      field: null,
      errorCode: "FILE_UNREADABLE",
      message: "ไม่สามารถอ่านไฟล์นี้ได้ กรุณาตรวจสอบรูปแบบไฟล์แล้วลองใหม่",
      severity: "error",
    },
  ],
  resultSummary: null,
};

// Status = cancelled (terminal).
const CANCELLED_FIXTURE: ImportSessionDetail = {
  id: "demo-cancelled",
  datasetType: "equipment_master",
  filename: "equipment-master-draft.xlsx",
  status: "cancelled",
  createdByUserId: "demo-user-2",
  requestedByDisplayName: "สมหญิง รักงาน",
  createdAt: "2026-03-01T06:00:00Z",
  totalRows: 60,
  validRows: 55,
  invalidRows: 0,
  warningRows: 5,
  importedRows: 0,
  requestedFileSizeBytes: 98_000,
  validationCounts: { totalRows: 60, validRows: 55, warningRows: 5, invalidRows: 0 },
  findingsByCategory: [],
  findings: [],
  resultSummary: {
    status: "cancelled",
    importedRows: 0,
    terminalAt: null,
    sessionId: "demo-cancelled",
  },
};

// Default representative seed set for the session list -- covers dry-run
// (confirm-gate), completed, completed-with-warnings, validation-failed,
// and cancelled, used both by the real dev-mode MockImportClient and
// directly by tests needing a full seed set.
export const legacyImportSkeletonFixtures: ImportSessionDetail[] = [
  DRY_RUN_COMPLETED_FIXTURE,
  COMPLETED_FIXTURE,
  COMPLETED_WITH_WARNINGS_FIXTURE,
  VALIDATION_FAILED_FIXTURE,
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
// file"). Lands directly on `dry_run_completed`, matching the real
// confirm-gate status rather than an invented intermediate one.
export function createMockImportSession(input: {
  importCategory: ImportCategory;
  file: SelectedFilePreview;
  requestedByDisplayName: string;
}): ImportSessionDetail {
  const totalRows = CATEGORY_DEMO_ROW_COUNTS[input.importCategory];
  const invalidRows = Math.round(totalRows * 0.03);
  const warningRows = Math.round(totalRows * 0.07);
  const validRows = totalRows - invalidRows;
  const status: ImportSessionStatus = "dry_run_completed";

  return {
    id: nextId("preview"),
    datasetType: input.importCategory,
    filename: input.file.name,
    status,
    createdByUserId: "demo-user-1",
    requestedByDisplayName: input.requestedByDisplayName,
    createdAt: new Date().toISOString(),
    totalRows,
    validRows,
    invalidRows,
    warningRows,
    importedRows: null,
    requestedFileSizeBytes: input.file.sizeBytes,
    validationCounts: { totalRows, validRows, warningRows, invalidRows },
    findingsByCategory: [
      { categoryLabelTh: "รูปแบบข้อมูลไม่ถูกต้อง (ตัวอย่าง)", count: invalidRows },
      { categoryLabelTh: "ไม่พบข้อมูลอ้างอิงที่ตรงกัน (ตัวอย่าง)", count: warningRows },
    ],
    findings: [
      {
        id: nextId("finding"),
        rowNumber: 7,
        field: "ตัวอย่างคอลัมน์",
        errorCode: "SAMPLE_ISSUE",
        message: "ตัวอย่างคำอธิบายปัญหา สำหรับต้นแบบหน้าจอเท่านั้น",
        severity: "error",
      },
      {
        id: nextId("finding"),
        rowNumber: 19,
        field: "ตัวอย่างคอลัมน์",
        errorCode: "SAMPLE_WARNING",
        message: "ตัวอย่างคำเตือน สำหรับต้นแบบหน้าจอเท่านั้น",
        severity: "warning",
      },
    ],
    resultSummary: null,
  };
}
