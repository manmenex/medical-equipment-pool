import { createMockImportSession, legacyImportSkeletonFixtures } from "@/services/legacyImportFixtures";
import type {
  ImportCategory,
  ImportSessionDetail,
  ImportSessionPage,
  ImportSessionSummary,
  SelectedFilePreview,
} from "@/types/legacyImport";

// PR19B skeleton only -- see types/legacyImport.ts's file-level note.
//
// LegacyImportClient is the one seam every PR19B page/component goes
// through. It never imports "@/services/api" and never issues an HTTP
// request -- there is no wiring to the real, now-merged PR19A endpoints in
// this skeleton (that integration is explicitly out of this task's scope).
// Once a real HttpLegacyImportClient implementing this same interface is
// authorized, it can replace MockImportClient below without any
// page/component change.
export interface LegacyImportClient {
  listSessions(): Promise<ImportSessionPage>;
  getSession(sessionId: string): Promise<ImportSessionDetail>;
  createPreviewSession(input: {
    importCategory: ImportCategory;
    file: SelectedFilePreview;
    requestedByDisplayName: string;
  }): Promise<ImportSessionDetail>;
}

export class ImportSessionNotFoundError extends Error {
  // Matches the real backend's IMPORT_SESSION_NOT_FOUND code
  // (docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md §23).
  readonly code = "IMPORT_SESSION_NOT_FOUND";

  constructor(sessionId: string) {
    super(`ไม่พบรายการนำเข้าข้อมูล: ${sessionId}`);
    this.name = "ImportSessionNotFoundError";
  }
}

const MOCK_LATENCY_MS = 300;

function delay<T>(value: T): Promise<T> {
  return new Promise((resolve) => {
    setTimeout(() => resolve(value), MOCK_LATENCY_MS);
  });
}

function toSummary(detail: ImportSessionDetail): ImportSessionSummary {
  return {
    id: detail.id,
    datasetType: detail.datasetType,
    filename: detail.filename,
    status: detail.status,
    createdByUserId: detail.createdByUserId,
    requestedByDisplayName: detail.requestedByDisplayName,
    createdAt: detail.createdAt,
    totalRows: detail.totalRows,
    validRows: detail.validRows,
    invalidRows: detail.invalidRows,
    warningRows: detail.warningRows,
    importedRows: detail.importedRows,
    failureReason: detail.failureReason,
  };
}

// MockImportClient: an isolated, obviously-named in-memory implementation.
// Never make this look like production behavior -- every page using it
// also renders the skeleton banner (components/LegacyImportSkeletonBanner)
// so a reviewer never mistakes this for a working importer.
export class MockImportClient implements LegacyImportClient {
  private readonly sessions = new Map<string, ImportSessionDetail>();

  constructor(seed: ImportSessionDetail[] = legacyImportSkeletonFixtures) {
    seed.forEach((session) => this.sessions.set(session.id, session));
  }

  async listSessions(): Promise<ImportSessionPage> {
    const items = Array.from(this.sessions.values())
      .sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1))
      .map(toSummary);
    // Mirrors the real Page[T] shape (backend/app/schemas/common.py) --
    // this mock never has more than one page of fixtures, so next_cursor
    // is always null.
    return delay({ items, nextCursor: null, total: items.length });
  }

  async getSession(sessionId: string): Promise<ImportSessionDetail> {
    const found = this.sessions.get(sessionId);
    if (!found) {
      return Promise.reject(new ImportSessionNotFoundError(sessionId));
    }
    return delay(found);
  }

  async createPreviewSession(input: {
    importCategory: ImportCategory;
    file: SelectedFilePreview;
    requestedByDisplayName: string;
  }): Promise<ImportSessionDetail> {
    const created = createMockImportSession(input);
    this.sessions.set(created.id, created);
    return delay(created);
  }
}

// The single instance every PR19B page imports. Swapping this line is the
// only change needed to point the skeleton at a real backend later.
export const legacyImportClient: LegacyImportClient = new MockImportClient();
