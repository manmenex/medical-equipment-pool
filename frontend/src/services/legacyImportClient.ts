import { createMockImportSession, legacyImportSkeletonFixtures } from "@/services/legacyImportFixtures";
import type { ImportCategory, ImportSessionDetail, ImportSessionSummary, SelectedFilePreview } from "@/types/legacyImport";

// PR19B skeleton only -- see types/legacyImport.ts's file-level note.
//
// LegacyImportClient is the one seam every PR19B page/component goes
// through. It never imports "@/services/api" and never issues an HTTP
// request -- there is no PR19A backend endpoint to call yet. Once PR19A's
// public API contract is approved and merged, a real HttpLegacyImportClient
// implementing this same interface can replace MockImportClient below
// without any page/component change.
export interface LegacyImportClient {
  listSessions(): Promise<ImportSessionSummary[]>;
  getSession(sessionId: string): Promise<ImportSessionDetail>;
  createPreviewSession(input: {
    importCategory: ImportCategory;
    file: SelectedFilePreview;
    requestedByDisplayName: string;
  }): Promise<ImportSessionDetail>;
}

export class ImportSessionNotFoundError extends Error {
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
    importCategory: detail.importCategory,
    filename: detail.filename,
    status: detail.status,
    requestedByDisplayName: detail.requestedByDisplayName,
    createdAt: detail.createdAt,
    totalRows: detail.totalRows,
    importedCount: detail.importedCount,
    skippedCount: detail.skippedCount,
    failedCount: detail.failedCount,
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

  async listSessions(): Promise<ImportSessionSummary[]> {
    const items = Array.from(this.sessions.values())
      .sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1))
      .map(toSummary);
    return delay(items);
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
