import { api } from "@/services/api";

// PR25E S3: thin client for the sync endpoints (docs/api/sync.md). Kept apart
// from the worker so wiring POST /sync/verify (B3) later is a one-function add.

export type SyncResultStatus = "applied" | "duplicate" | "conflict" | "rejected" | "retry_later";

export interface SyncOperationResult {
  op_id: string;
  result: SyncResultStatus;
  code: string;
  transaction_id?: string | null;
  message?: string;
}

export const MAX_BATCH_OPS = 25;

export async function postOperations(envelopes: Record<string, unknown>[]): Promise<SyncOperationResult[]> {
  const resp = await api.post<{ results: SyncOperationResult[] }>("/sync/operations", {
    operations: envelopes,
  });
  return resp.data.results;
}

// ---- reference snapshot (slice B3, docs/api/sync.md) -----------------------

export const SNAPSHOT_SECTIONS = ["equipment", "wards", "departments", "locations", "open_transactions"] as const;
export type SnapshotSection = (typeof SNAPSHOT_SECTIONS)[number];

export interface SnapshotPage {
  section: SnapshotSection;
  items: Array<{ id: string } & Record<string, unknown>>;
  next_cursor: string | null;
  etag: string;
  server_time: string;
}

export type SnapshotFetch = { notModified: true } | { notModified: false; page: SnapshotPage; etag: string };

/** One page. A matching `etag` yields `{ notModified: true }` (HTTP 304, no body). */
export async function fetchSnapshotPage(
  section: SnapshotSection,
  opts: { cursor?: string | null; etag?: string | null; limit?: number } = {},
): Promise<SnapshotFetch> {
  const resp = await api.get<SnapshotPage>("/sync/snapshot", {
    params: { section, cursor: opts.cursor ?? undefined, limit: opts.limit ?? 200 },
    headers: opts.etag ? { "If-None-Match": opts.etag } : undefined,
    validateStatus: (s) => (s >= 200 && s < 300) || s === 304,
  });
  if (resp.status === 304) return { notModified: true };
  const header = (resp.headers as Record<string, unknown> | undefined)?.["etag"];
  return { notModified: false, page: resp.data, etag: typeof header === "string" && header ? header : resp.data.etag };
}
