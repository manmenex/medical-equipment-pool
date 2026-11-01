import "fake-indexeddb/auto";

import { IDBFactory } from "fake-indexeddb";
import { openDB } from "idb";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  applyUpdateIfSafe,
  getUpdateState,
  markClientTooOld,
  registerFormDirty,
  resetAppUpdate,
  setUpdateReady,
  updateBlockReason,
} from "./appUpdate";
import {
  closeOfflineDb,
  DB_NAME,
  DB_VERSION,
  enqueueOperation,
  listOutbox,
  listSendable,
  MIGRATION_COUNT,
  openOfflineDb,
  REF_STORES,
  updateOutbox,
} from "./offlineStore";

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
  resetAppUpdate();
});
afterEach(async () => {
  await closeOfflineDb();
});

describe("update safety (design 13.3)", () => {
  it("applies when idle: no ops, no dirty form, not sending", async () => {
    const apply = vi.fn(async () => undefined);
    setUpdateReady(apply);
    expect(getUpdateState().ready).toBe(true);
    expect(await applyUpdateIfSafe(false)).toBeNull();
    expect(apply).toHaveBeenCalledOnce();
  });

  it("never applies while ops are pending, sending or held; the outbox survives", async () => {
    const apply = vi.fn(async () => undefined);
    setUpdateReady(apply);
    const rec = await enqueueOperation("u1", { body: { op_type: "dispatch" } });
    expect(await applyUpdateIfSafe(false)).toBe("ops_pending");
    await updateOutbox("u1", rec.op_id, { state: "sending" });
    expect(await applyUpdateIfSafe(false)).toBe("ops_pending");
    await updateOutbox("u1", rec.op_id, { state: "held", blocked_by: "x" });
    expect(await applyUpdateIfSafe(false)).toBe("ops_pending");
    expect(apply).not.toHaveBeenCalled();
    expect(await listOutbox("u1")).toHaveLength(1);
  });

  it("counts other users' ops too (shared device)", async () => {
    await enqueueOperation("someone-else", { body: { op_type: "dispatch" } });
    expect(await updateBlockReason(false)).toBe("ops_pending");
  });

  it("conflict rows (not deliverable) do not block", async () => {
    const rec = await enqueueOperation("u1", { body: { op_type: "dispatch" } });
    await updateOutbox("u1", rec.op_id, { state: "conflict" });
    expect(await updateBlockReason(false)).toBeNull();
  });

  it("never applies while a form is dirty or the sync worker is mid-send", async () => {
    const apply = vi.fn(async () => undefined);
    setUpdateReady(apply);
    const release = registerFormDirty(Symbol("f"), true);
    expect(await applyUpdateIfSafe(false)).toBe("form_dirty");
    release();
    expect(await applyUpdateIfSafe(true)).toBe("sync_sending");
    expect(apply).not.toHaveBeenCalled();
    expect(await applyUpdateIfSafe(false)).toBeNull();
  });

  it("does not apply when the queue cannot be read", async () => {
    const saved = globalThis.indexedDB;
    // @ts-expect-error simulate a browser without IndexedDB
    delete globalThis.indexedDB;
    setUpdateReady(vi.fn(async () => undefined));
    expect(await applyUpdateIfSafe(false)).toBe("storage_unreadable");
    globalThis.indexedDB = saved;
  });

  it("CLIENT_TOO_OLD with a queue blocked by it still applies (no deadlock); dirty form still blocks", async () => {
    const apply = vi.fn(async () => undefined);
    setUpdateReady(apply);
    await enqueueOperation("u1", { body: { op_type: "dispatch" } });
    expect(await updateBlockReason(false)).toBe("ops_pending");
    markClientTooOld();
    const release = registerFormDirty(Symbol("f"), true);
    expect(await applyUpdateIfSafe(false)).toBe("form_dirty");
    release();
    expect(await applyUpdateIfSafe(true)).toBe("sync_sending");
    expect(await applyUpdateIfSafe(false)).toBeNull();
    expect(apply).toHaveBeenCalledOnce();
    expect(await listOutbox("u1")).toHaveLength(1);
  });

  it("re-checks the sync worker right before applying", async () => {
    const apply = vi.fn(async () => undefined);
    setUpdateReady(apply);
    let calls = 0;
    expect(await applyUpdateIfSafe(() => ++calls > 1)).toBe("sync_sending");
    expect(apply).not.toHaveBeenCalled();
  });

  it("CLIENT_TOO_OLD flags the update as required", () => {
    markClientTooOld();
    expect(getUpdateState().required).toBe(true);
  });
});

describe("IndexedDB schema versioning", () => {
  it("has exactly one migration step per version", () => {
    expect(MIGRATION_COUNT).toBe(DB_VERSION);
  });

  it("upgrades a database left by the previous app version without losing outbox rows", async () => {
    // The v1 layout exactly as the shipped S2 app created it, holding a row
    // queued before S6 (no envelope_version, no stale_context).
    const v1 = await openDB(DB_NAME, 1, {
      upgrade(db) {
        db.createObjectStore("meta", { keyPath: "name" });
        const outbox = db.createObjectStore("outbox", { keyPath: "op_id" });
        outbox.createIndex("by_user", "user_id");
        outbox.createIndex("by_seq", "device_seq");
        const journal = db.createObjectStore("journal", { keyPath: "op_id" });
        journal.createIndex("by_user", "user_id");
        journal.createIndex("by_acked_at", "acked_at");
        for (const n of REF_STORES) db.createObjectStore(n, { keyPath: "id" });
      },
    });
    await v1.put("meta", { name: "device_id", value: "11111111-1111-4111-8111-111111111111" });
    await v1.put("meta", { name: "device_seq", value: 1 });
    await v1.put("outbox", {
      op_id: "22222222-2222-4222-8222-222222222222",
      user_id: "u1",
      device_seq: 1,
      state: "pending",
      attempt_count: 0,
      last_error_code: null,
      blocked_by: null,
      created_at: 1,
      envelope: { op_id: "22222222-2222-4222-8222-222222222222", op_type: "dispatch", user_id: "u1" },
    });
    v1.close();

    const db = await openOfflineDb();
    expect(db.version).toBe(DB_VERSION);
    const rows = await listOutbox("u1");
    expect(rows).toHaveLength(1);
    // The server treats a missing envelope_version as 1.
    expect(rows[0].envelope).not.toHaveProperty("envelope_version");
    expect((await listSendable("u1")).map((r) => r.op_id)).toEqual(["22222222-2222-4222-8222-222222222222"]);
    const next = await enqueueOperation("u1", { body: { op_type: "dispatch" } });
    expect(next.device_seq).toBe(2);
  });
});
