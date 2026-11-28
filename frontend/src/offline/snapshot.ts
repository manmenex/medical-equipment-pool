import { fetchSnapshotPage, SNAPSHOT_SECTIONS, type SnapshotSection } from "@/services/syncClient";
import { useAuthStore, whenLogoutWipeDone } from "@/store/authStore";

import {
  getMeta,
  pruneRefsExcept,
  setMeta,
  SNAPSHOT_PAGE_PREFIX,
  upsertRefs,
  type RefStoreName,
} from "./offlineStore";
import { recordServerTime } from "./serverTime";

// PR25E S4 (design 3.2, 6.5): reference snapshot refresh into the ref_* stores.
//
// Paging is NOT point-in-time (docs/api/sync.md), so pages are upserted by id
// and, only after a section's scan completes without error, rows that were not
// seen in the scan are pruned ("full refresh"). Each page's ETag, next cursor
// and id list are remembered in meta so a 304 (no body) can still be followed
// to the next page and still counts its rows as seen.

export const SECTION_STORE: Record<SnapshotSection, RefStoreName> = {
  equipment: "ref_equipment",
  wards: "ref_wards",
  departments: "ref_departments",
  locations: "ref_locations",
  open_transactions: "ref_open_tx",
};
export const REFRESH_INTERVAL_MS = 15 * 60 * 1000;
const MAX_PAGES_PER_SECTION = 1000; // loop guard against a cursor cycle

interface PageMeta {
  etag: string;
  next_cursor: string | null;
  ids: string[];
}

function pageKey(section: SnapshotSection, cursor: string | null): string {
  return `${SNAPSHOT_PAGE_PREFIX}${section}:${cursor ?? ""}`;
}

function currentUserId(): string | null {
  const { user, accessToken } = useAuthStore.getState();
  return user && accessToken ? String(user.id) : null;
}

export interface RefreshResult {
  pagesFetched: number;
  pagesNotModified: number;
  rowsWritten: number;
  rowsPruned: number;
}

class Aborted extends Error {}

async function refreshSection(section: SnapshotSection, userId: string, out: RefreshResult): Promise<void> {
  const store = SECTION_STORE[section];
  const seen = new Set<string>();
  let cursor: string | null = null;
  for (let i = 0; i < MAX_PAGES_PER_SECTION; i++) {
    const key = pageKey(section, cursor);
    const known = await getMeta<PageMeta>(key);
    const res = await fetchSnapshotPage(section, { cursor, etag: known?.etag ?? null });
    // Logout / user switch mid-scan: write nothing more (the wipe owns the stores).
    if (currentUserId() !== userId) throw new Aborted();
    if (res.notModified) {
      if (!known) throw new Error("snapshot 304 without a remembered page");
      out.pagesNotModified++;
      known.ids.forEach((id) => seen.add(id));
      cursor = known.next_cursor;
    } else {
      const { page, etag } = res;
      out.pagesFetched++;
      await upsertRefs(store, page.items);
      out.rowsWritten += page.items.length;
      page.items.forEach((r) => seen.add(r.id));
      await setMeta(key, { etag, next_cursor: page.next_cursor, ids: page.items.map((r) => r.id) } satisfies PageMeta);
      const serverMs = Date.parse(page.server_time);
      if (!Number.isNaN(serverMs)) await recordServerTime(serverMs, Date.now(), { force: true });
      cursor = page.next_cursor;
    }
    if (cursor === null) {
      if (currentUserId() !== userId) throw new Aborted();
      out.rowsPruned += await pruneRefsExcept(store, seen);
      return;
    }
  }
  throw new Error("snapshot paging did not terminate");
}

let inFlight: Promise<RefreshResult | null> | null = null;

/**
 * Refresh every section. Resolves null when skipped (no user / already running)
 * or when the user changed mid-run. `last_snapshot_at` is set only after ALL
 * sections completed, so a partial scan never makes the data look fresh.
 * Rejects on network/storage failure (callers retry on the next trigger).
 */
export function refreshSnapshot(): Promise<RefreshResult | null> {
  const userId = currentUserId();
  if (!userId) return Promise.resolve(null);
  if (inFlight) return inFlight;
  const out: RefreshResult = { pagesFetched: 0, pagesNotModified: 0, rowsWritten: 0, rowsPruned: 0 };
  inFlight = (async () => {
    try {
      await whenLogoutWipeDone(); // a previous logout's wipe must not eat this refresh
      for (const section of SNAPSHOT_SECTIONS) await refreshSection(section, userId, out);
      if (currentUserId() !== userId) return null;
      await setMeta("last_snapshot_at", Date.now());
      return out;
    } catch (e) {
      if (e instanceof Aborted) return null;
      throw e;
    } finally {
      inFlight = null;
    }
  })();
  return inFlight;
}

/** Triggers: login, online event, every 15 min. Returns a stop function. */
export function startSnapshotRefresh(): () => void {
  const run = () => void refreshSnapshot().catch(() => undefined);
  const onOnline = () => run();
  window.addEventListener("online", onOnline);
  const timer = setInterval(run, REFRESH_INTERVAL_MS);
  const unsub = useAuthStore.subscribe((s, prev) => {
    if (s.user?.id && s.user.id !== prev.user?.id) run();
  });
  run();
  return () => {
    window.removeEventListener("online", onOnline);
    clearInterval(timer);
    unsub();
  };
}
