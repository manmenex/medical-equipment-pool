import { deleteDB, openDB, type DBSchema, type IDBPDatabase } from "idb";

// PR25E S2 (docs/design/PR25D_OFFLINE_OPERATION_PLAN.md sections 7.1, 8, 12.2,
// 15 #18): the IndexedDB client store. No UI, no sync loop (S3), no snapshot
// fetching (S4). This module only persists:
//   meta     device_id, device_seq counter, snapshot bookkeeping
//   outbox   per-user queued operations, ordered by device_seq
//   journal  acked/discarded operations, kept 48 h from ack
//   ref_*    reference snapshot rows (wiped on logout)

export const DB_NAME = "mep-offline";
/** Bump together with a new entry in MIGRATIONS. */
export const DB_VERSION = 1;
export const MAX_OUTBOX_OPS = 500;
export const JOURNAL_RETENTION_MS = 48 * 60 * 60 * 1000;

export const REF_STORES = [
  "ref_equipment",
  "ref_wards",
  "ref_departments",
  "ref_locations",
  "ref_open_tx",
] as const;
export type RefStoreName = (typeof REF_STORES)[number];

export type OutboxState = "pending" | "sending" | "held" | "conflict" | "rejected";

export interface OutboxRecord {
  op_id: string;
  user_id: string;
  device_seq: number;
  state: OutboxState;
  attempt_count: number;
  last_error_code: string | null;
  blocked_by: string | null;
  created_at: number;
  envelope: Record<string, unknown>;
}

export interface JournalRecord {
  op_id: string;
  user_id: string;
  device_seq: number;
  kind: "acked" | "discarded";
  envelope: Record<string, unknown>;
  result: Record<string, unknown> | null;
  acked_at: number;
}

interface MetaRecord {
  name: string;
  value: unknown;
}

interface OfflineDB extends DBSchema {
  meta: { key: string; value: MetaRecord };
  outbox: {
    key: string;
    value: OutboxRecord;
    indexes: { by_user: string; by_seq: number };
  };
  journal: {
    key: string;
    value: JournalRecord;
    indexes: { by_user: string; by_acked_at: number };
  };
  ref_equipment: { key: string; value: { id: string } & Record<string, unknown> };
  ref_wards: { key: string; value: { id: string } & Record<string, unknown> };
  ref_departments: { key: string; value: { id: string } & Record<string, unknown> };
  ref_locations: { key: string; value: { id: string } & Record<string, unknown> };
  ref_open_tx: { key: string; value: { id: string } & Record<string, unknown> };
}

export type OfflineStoreErrorCode =
  | "STORAGE_UNAVAILABLE"
  | "QUOTA_EXCEEDED"
  | "QUEUE_FULL"
  | "STORE_TOO_NEW"
  | "NOT_FOUND"
  | "STORAGE_ERROR";

export class OfflineStoreError extends Error {
  readonly code: OfflineStoreErrorCode;
  constructor(code: OfflineStoreErrorCode, message: string, options?: { cause?: unknown }) {
    super(message);
    if (options && "cause" in options) (this as { cause?: unknown }).cause = options.cause;
    this.name = "OfflineStoreError";
    this.code = code;
  }
}

type Upgrade = (db: IDBPDatabase<OfflineDB>) => void;

// Forward-only upgrade steps, index = target version - 1. The outbox is
// migrated forward, never dropped (design section 13). Each step must be
// able to run on a database that is at exactly the previous version.
const MIGRATIONS: Upgrade[] = [
  // v1: initial schema (from empty).
  (db) => {
    db.createObjectStore("meta", { keyPath: "name" });
    const outbox = db.createObjectStore("outbox", { keyPath: "op_id" });
    outbox.createIndex("by_user", "user_id");
    outbox.createIndex("by_seq", "device_seq");
    const journal = db.createObjectStore("journal", { keyPath: "op_id" });
    journal.createIndex("by_user", "user_id");
    journal.createIndex("by_acked_at", "acked_at");
    for (const name of REF_STORES) db.createObjectStore(name, { keyPath: "id" });
  },
];

let dbPromise: Promise<IDBPDatabase<OfflineDB>> | null = null;

function classify(error: unknown, fallback = "Offline storage failed"): OfflineStoreError {
  if (error instanceof OfflineStoreError) return error;
  const name = (error as { name?: string } | null)?.name;
  if (name === "QuotaExceededError") {
    return new OfflineStoreError("QUOTA_EXCEEDED", "Device storage is full", { cause: error });
  }
  if (name === "VersionError") {
    return new OfflineStoreError(
      "STORE_TOO_NEW",
      "Offline data was written by a newer app version; reload to update",
      { cause: error },
    );
  }
  if (name === "SecurityError" || name === "InvalidStateError" || name === "UnknownError") {
    return new OfflineStoreError("STORAGE_UNAVAILABLE", "Offline storage is unavailable", { cause: error });
  }
  return new OfflineStoreError("STORAGE_ERROR", fallback, { cause: error });
}

export function openOfflineDb(): Promise<IDBPDatabase<OfflineDB>> {
  if (dbPromise) return dbPromise;
  if (typeof indexedDB === "undefined") {
    return Promise.reject(new OfflineStoreError("STORAGE_UNAVAILABLE", "IndexedDB is not available"));
  }
  const p = openDB<OfflineDB>(DB_NAME, DB_VERSION, {
    upgrade(db, oldVersion, newVersion) {
      for (let v = oldVersion; v < (newVersion ?? DB_VERSION); v++) MIGRATIONS[v](db);
    },
    blocked() {
      /* another tab holds an older connection; open resolves when it closes */
    },
    terminated() {
      dbPromise = null;
    },
  }).then((db) => {
    // Let a newer tab upgrade: close our connection and reopen lazily.
    db.addEventListener("versionchange", () => {
      db.close();
      dbPromise = null;
    });
    return db;
  });
  dbPromise = p.catch((e) => {
    dbPromise = null;
    throw classify(e);
  });
  return dbPromise;
}

/** Close the cached connection (tests, "reload" simulation). */
export async function closeOfflineDb(): Promise<void> {
  const p = dbPromise;
  dbPromise = null;
  if (p) (await p.catch(() => null))?.close();
}

/** "Remove all data from this device" (design 12.2): drops everything incl. device_id. */
export async function deleteOfflineDb(): Promise<void> {
  await closeOfflineDb();
  try {
    await deleteDB(DB_NAME);
  } catch (e) {
    throw classify(e);
  }
}

async function guarded<T>(fn: (db: IDBPDatabase<OfflineDB>) => Promise<T>): Promise<T> {
  try {
    return await fn(await openOfflineDb());
  } catch (e) {
    throw classify(e);
  }
}

function newUuid(): string {
  return globalThis.crypto.randomUUID();
}

export async function getMeta<T = unknown>(name: string): Promise<T | undefined> {
  return guarded(async (db) => (await db.get("meta", name))?.value as T | undefined);
}

export async function setMeta(name: string, value: unknown): Promise<void> {
  return guarded(async (db) => {
    await db.put("meta", { name, value });
  });
}

/** Stable per-browser-profile id; created on first call. */
export async function getDeviceId(): Promise<string> {
  return guarded(async (db) => {
    const tx = db.transaction("meta", "readwrite");
    tx.done.catch(() => undefined); // failures surface via the awaited operations
    let rec = await tx.store.get("device_id");
    if (!rec) {
      rec = { name: "device_id", value: newUuid() };
      await tx.store.put(rec);
    }
    await tx.done;
    return rec.value as string;
  });
}

export interface EnqueueInput {
  /** Defaults to a fresh UUID v4. */
  op_id?: string;
  /** Business body of the envelope (op_type, dispatch/receipt, times ...). */
  body: Record<string, unknown>;
}

/**
 * Atomically: enforce the device cap, bump device_seq, create device_id if
 * needed, and write the outbox row (design 7.2). Throws QUEUE_FULL at the cap
 * and QUOTA_EXCEEDED when the browser refuses the write; in both cases
 * nothing is written and device_seq is not consumed.
 */
export async function enqueueOperation(
  userId: string,
  input: EnqueueInput,
  now: number = Date.now(),
): Promise<OutboxRecord> {
  return guarded(async (db) => {
    const tx = db.transaction(["meta", "outbox"], "readwrite");
    tx.done.catch(() => undefined); // failures surface via the awaited operations
    try {
      const count = await tx.objectStore("outbox").count();
      if (count >= MAX_OUTBOX_OPS) {
        tx.abort();
        await tx.done.catch(() => undefined);
        throw new OfflineStoreError(
          "QUEUE_FULL",
          `Offline queue is full (${MAX_OUTBOX_OPS}); use paper and enter later`,
        );
      }
      const meta = tx.objectStore("meta");
      let deviceId = (await meta.get("device_id"))?.value as string | undefined;
      if (!deviceId) {
        deviceId = newUuid();
        await meta.put({ name: "device_id", value: deviceId });
      }
      const seq = (((await meta.get("device_seq"))?.value as number | undefined) ?? 0) + 1;
      await meta.put({ name: "device_seq", value: seq });
      const op_id = input.op_id ?? newUuid();
      const record: OutboxRecord = {
        op_id,
        user_id: userId,
        device_seq: seq,
        state: "pending",
        attempt_count: 0,
        last_error_code: null,
        blocked_by: null,
        created_at: now,
        envelope: { ...input.body, op_id, device_id: deviceId, device_seq: seq },
      };
      await tx.objectStore("outbox").add(record);
      await tx.done;
      return record;
    } catch (e) {
      try {
        tx.abort();
      } catch {
        /* already finished/aborted */
      }
      throw e;
    }
  });
}

/** The user's outbox rows in device_seq order. Never returns other users' rows. */
export async function listOutbox(userId: string): Promise<OutboxRecord[]> {
  return guarded(async (db) => {
    const rows = await db.getAllFromIndex("outbox", "by_user", userId);
    return rows.sort((a, b) => a.device_seq - b.device_seq);
  });
}

/** The user's sendable ops (state `pending`) in device_seq order. */
export async function listSendable(userId: string): Promise<OutboxRecord[]> {
  return (await listOutbox(userId)).filter((r) => r.state === "pending");
}

/** Count of this device's outbox rows across all users (the cap basis) and for one user. */
export async function countOutbox(userId?: string): Promise<number> {
  return guarded(async (db) =>
    userId === undefined ? db.count("outbox") : db.countFromIndex("outbox", "by_user", userId),
  );
}

export interface OutboxPatch {
  state?: OutboxState;
  attempt_count?: number;
  last_error_code?: string | null;
  blocked_by?: string | null;
}

export async function updateOutbox(userId: string, opId: string, patch: OutboxPatch): Promise<OutboxRecord> {
  return guarded(async (db) => {
    const tx = db.transaction("outbox", "readwrite");
    tx.done.catch(() => undefined); // failures surface via the awaited operations
    const rec = await tx.store.get(opId);
    if (!rec || rec.user_id !== userId) {
      tx.abort();
      await tx.done.catch(() => undefined);
      throw new OfflineStoreError("NOT_FOUND", "Operation not found for this user");
    }
    const next = { ...rec, ...patch };
    await tx.store.put(next);
    await tx.done;
    return next;
  });
}

async function moveToJournal(
  userId: string,
  opId: string,
  kind: JournalRecord["kind"],
  result: Record<string, unknown> | null,
  now: number,
): Promise<JournalRecord> {
  return guarded(async (db) => {
    const tx = db.transaction(["outbox", "journal"], "readwrite");
    tx.done.catch(() => undefined); // failures surface via the awaited operations
    const rec = await tx.objectStore("outbox").get(opId);
    if (!rec || rec.user_id !== userId) {
      tx.abort();
      await tx.done.catch(() => undefined);
      throw new OfflineStoreError("NOT_FOUND", "Operation not found for this user");
    }
    const entry: JournalRecord = {
      op_id: rec.op_id,
      user_id: rec.user_id,
      device_seq: rec.device_seq,
      kind,
      envelope: rec.envelope,
      result,
      acked_at: now,
    };
    await tx.objectStore("journal").put(entry);
    await tx.objectStore("outbox").delete(opId);
    await tx.done;
    return entry;
  });
}

/** Server acked (`applied` or `duplicate`): outbox -> journal, atomically. */
export function ackOperation(
  userId: string,
  opId: string,
  result: Record<string, unknown>,
  now: number = Date.now(),
): Promise<JournalRecord> {
  return moveToJournal(userId, opId, "acked", result, now);
}

/** Operator discards their own queued op (local only; journaled as `discarded`). */
export function discardOperation(userId: string, opId: string, now: number = Date.now()): Promise<JournalRecord> {
  return moveToJournal(userId, opId, "discarded", null, now);
}

/** The user's journal rows still inside the 48 h window, newest first. */
export async function listJournal(userId: string, now: number = Date.now()): Promise<JournalRecord[]> {
  return guarded(async (db) => {
    const rows = await db.getAllFromIndex("journal", "by_user", userId);
    return rows
      .filter((r) => now - r.acked_at <= JOURNAL_RETENTION_MS)
      .sort((a, b) => b.acked_at - a.acked_at);
  });
}

/** Delete journal rows older than 48 h from ack (all users). Returns count removed. */
export async function pruneJournal(now: number = Date.now()): Promise<number> {
  return guarded(async (db) => {
    const tx = db.transaction("journal", "readwrite");
    tx.done.catch(() => undefined); // failures surface via the awaited operations
    const range = IDBKeyRange.upperBound(now - JOURNAL_RETENTION_MS, true);
    let removed = 0;
    let cursor = await tx.store.index("by_acked_at").openCursor(range);
    while (cursor) {
      await cursor.delete();
      removed++;
      cursor = await cursor.continue();
    }
    await tx.done;
    return removed;
  });
}

// ---- reference snapshot store -------------------------------------------

/** Replace the whole contents of one ref store atomically. */
export async function replaceRefs(
  store: RefStoreName,
  rows: Array<{ id: string } & Record<string, unknown>>,
): Promise<void> {
  return guarded(async (db) => {
    const tx = db.transaction(store, "readwrite");
    tx.done.catch(() => undefined); // failures surface via the awaited operations
    await tx.store.clear();
    for (const row of rows) await tx.store.put(row);
    await tx.done;
  });
}

export async function listRefs(store: RefStoreName): Promise<Array<{ id: string } & Record<string, unknown>>> {
  return guarded((db) => db.getAll(store));
}

export async function getRef(store: RefStoreName, id: string) {
  return guarded((db) => db.get(store, id));
}

/**
 * Logout wipe (design 8.2 / 12.2): clears every ref_* store and snapshot
 * bookkeeping. Deliberately KEEPS outbox, journal, device_id and device_seq:
 * unsynced operations are real equipment movements and must survive logout.
 */
export async function wipeOnLogout(): Promise<void> {
  return guarded(async (db) => {
    const tx = db.transaction([...REF_STORES, "meta"], "readwrite");
    tx.done.catch(() => undefined); // failures surface via the awaited operations
    for (const name of REF_STORES) await tx.objectStore(name).clear();
    await tx.objectStore("meta").delete("last_snapshot_at");
    await tx.done;
  });
}
