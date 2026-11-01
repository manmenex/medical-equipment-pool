import "fake-indexeddb/auto";

import { IDBFactory } from "fake-indexeddb";
import { openDB } from "idb";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  ackOperation,
  closeOfflineDb,
  countOutbox,
  DB_NAME,
  deleteOfflineDb,
  discardOperation,
  enqueueOperation,
  getDeviceId,
  getMeta,
  getRef,
  JOURNAL_RETENTION_MS,
  listJournal,
  listOutbox,
  listRefs,
  listSendable,
  MAX_OUTBOX_OPS,
  OfflineStoreError,
  openOfflineDb,
  pruneJournal,
  replaceRefs,
  setMeta,
  updateOutbox,
  wipeOnLogout,
} from "./offlineStore";

const body = (n: number) => ({ op_type: "dispatch", dispatch: { n } });

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
});

afterEach(async () => {
  await closeOfflineDb();
});

describe("schema", () => {
  it("creates all stores from an empty database", async () => {
    const db = await openOfflineDb();
    expect([...db.objectStoreNames].sort()).toEqual(
      ["journal", "meta", "outbox", "ref_departments", "ref_equipment", "ref_locations", "ref_open_tx", "ref_wards"].sort(),
    );
    expect(db.version).toBe(1);
  });

  it("rejects a database written by a newer version without touching it", async () => {
    const newer = await openDB(DB_NAME, 99, {
      upgrade(db) {
        db.createObjectStore("future");
      },
    });
    newer.close();
    await expect(openOfflineDb()).rejects.toMatchObject({ code: "STORE_TOO_NEW" });
    const check = await openDB(DB_NAME);
    expect(check.version).toBe(99);
    check.close();
  });

  it("reports unavailable storage", async () => {
    const saved = globalThis.indexedDB;
    // @ts-expect-error simulate a browser without IndexedDB
    delete globalThis.indexedDB;
    await expect(openOfflineDb()).rejects.toMatchObject({ code: "STORAGE_UNAVAILABLE" });
    globalThis.indexedDB = saved;
  });
});

describe("outbox", () => {
  it("dequeues in device_seq order with a complete envelope", async () => {
    const a = await enqueueOperation("u1", { body: body(1) });
    const b = await enqueueOperation("u1", { body: body(2) });
    const c = await enqueueOperation("u1", { body: body(3) });
    expect([a.device_seq, b.device_seq, c.device_seq]).toEqual([1, 2, 3]);
    const rows = await listSendable("u1");
    expect(rows.map((r) => r.op_id)).toEqual([a.op_id, b.op_id, c.op_id]);
    expect(rows[0].envelope).toMatchObject({
      op_id: a.op_id,
      device_id: await getDeviceId(),
      device_seq: 1,
      op_type: "dispatch",
    });
    await updateOutbox("u1", b.op_id, { state: "held", blocked_by: a.op_id });
    expect((await listSendable("u1")).map((r) => r.op_id)).toEqual([a.op_id, c.op_id]);
  });

  it("isolates users: no reads, updates, acks or discards across users", async () => {
    const a = await enqueueOperation("u1", { body: body(1) });
    const b = await enqueueOperation("u2", { body: body(2) });
    expect((await listOutbox("u1")).map((r) => r.op_id)).toEqual([a.op_id]);
    expect((await listOutbox("u2")).map((r) => r.op_id)).toEqual([b.op_id]);
    await expect(updateOutbox("u2", a.op_id, { state: "sending" })).rejects.toMatchObject({ code: "NOT_FOUND" });
    await expect(ackOperation("u2", a.op_id, {})).rejects.toMatchObject({ code: "NOT_FOUND" });
    await expect(discardOperation("u2", a.op_id)).rejects.toMatchObject({ code: "NOT_FOUND" });
    expect((await listOutbox("u1"))[0].state).toBe("pending");
    expect(await listJournal("u2")).toEqual([]);
  });

  it("keeps device_id stable and device_seq monotonic across reloads", async () => {
    const a = await enqueueOperation("u1", { body: body(1) });
    const id1 = await getDeviceId();
    await closeOfflineDb();
    const b = await enqueueOperation("u2", { body: body(2) });
    await ackOperation("u1", a.op_id, { result: "applied" });
    await closeOfflineDb();
    const c = await enqueueOperation("u1", { body: body(3) });
    expect([a.device_seq, b.device_seq, c.device_seq]).toEqual([1, 2, 3]);
    expect(await getDeviceId()).toBe(id1);
    expect(c.envelope.device_id).toBe(id1);
  });

  it("enforces the device-wide cap and does not consume device_seq when refused", async () => {
    for (let i = 0; i < MAX_OUTBOX_OPS; i++) {
      await enqueueOperation(i % 2 ? "u1" : "u2", { body: body(i) });
    }
    expect(await countOutbox()).toBe(MAX_OUTBOX_OPS);
    await expect(enqueueOperation("u1", { body: body(-1) })).rejects.toMatchObject({ code: "QUEUE_FULL" });
    expect(await countOutbox()).toBe(MAX_OUTBOX_OPS);
    expect(await getMeta("device_seq")).toBe(MAX_OUTBOX_OPS);
    // Acking frees a slot; the next op continues the sequence.
    const first = (await listOutbox("u2"))[0];
    await ackOperation("u2", first.op_id, {});
    const next = await enqueueOperation("u1", { body: body(0) });
    expect(next.device_seq).toBe(MAX_OUTBOX_OPS + 1);
  }, 60000);

  it("rejects a reused op_id without consuming a sequence number", async () => {
    const a = await enqueueOperation("u1", { body: body(1) });
    await expect(enqueueOperation("u1", { op_id: a.op_id, body: body(2) })).rejects.toBeInstanceOf(OfflineStoreError);
    expect(await getMeta("device_seq")).toBe(1);
  });
});

describe("journal", () => {
  it("moves acked and discarded ops out of the outbox into the journal", async () => {
    const a = await enqueueOperation("u1", { body: body(1) });
    const b = await enqueueOperation("u1", { body: body(2) });
    await ackOperation("u1", a.op_id, { result: "applied" }, 1000);
    await discardOperation("u1", b.op_id, 2000);
    expect(await listOutbox("u1")).toEqual([]);
    const j = await listJournal("u1", 3000);
    expect(j.map((r) => [r.op_id, r.kind])).toEqual([
      [b.op_id, "discarded"],
      [a.op_id, "acked"],
    ]);
    expect(j[1].result).toEqual({ result: "applied" });
  });

  it("prunes at 48h from ack", async () => {
    const a = await enqueueOperation("u1", { body: body(1) });
    const b = await enqueueOperation("u2", { body: body(2) });
    const c = await enqueueOperation("u1", { body: body(3) });
    const t0 = 1_000_000_000;
    await ackOperation("u1", a.op_id, {}, t0);
    await ackOperation("u2", b.op_id, {}, t0 + 1000);
    await ackOperation("u1", c.op_id, {}, t0 + JOURNAL_RETENTION_MS);
    // Exactly 48h after a's ack: still kept.
    expect(await pruneJournal(t0 + JOURNAL_RETENTION_MS)).toBe(0);
    // 1 ms later a is gone; b (acked 1 s later) is kept, c kept.
    expect(await pruneJournal(t0 + JOURNAL_RETENTION_MS + 1)).toBe(1);
    expect((await listJournal("u1", t0 + JOURNAL_RETENTION_MS + 1)).map((r) => r.op_id)).toEqual([c.op_id]);
    expect(await pruneJournal(t0 + JOURNAL_RETENTION_MS + 1001)).toBe(1);
    expect(await listJournal("u2", t0 + JOURNAL_RETENTION_MS + 1001)).toEqual([]);
  });

  it("hides expired entries from listJournal even before pruning", async () => {
    const a = await enqueueOperation("u1", { body: body(1) });
    await ackOperation("u1", a.op_id, {}, 0);
    expect(await listJournal("u1", JOURNAL_RETENTION_MS + 1)).toEqual([]);
  });
});

describe("reference store and logout wipe", () => {
  it("replaces ref rows wholesale", async () => {
    await replaceRefs("ref_wards", [{ id: "w1", name: "A" }, { id: "w2", name: "B" }]);
    await replaceRefs("ref_wards", [{ id: "w3", name: "C" }]);
    expect((await listRefs("ref_wards")).map((r) => r.id)).toEqual(["w3"]);
    expect(await getRef("ref_wards", "w3")).toMatchObject({ name: "C" });
  });

  it("wipes refs and snapshot time but keeps outbox, journal and device identity", async () => {
    const a = await enqueueOperation("u1", { body: body(1) });
    const b = await enqueueOperation("u1", { body: body(2) });
    await ackOperation("u1", b.op_id, {}, Date.now());
    const deviceId = await getDeviceId();
    await replaceRefs("ref_equipment", [{ id: "e1", bcm_code: "BCM1" }]);
    await replaceRefs("ref_open_tx", [{ id: "t1" }]);
    await setMeta("last_snapshot_at", 123);
    await setMeta("clock_offset", { ms: 5 });

    await wipeOnLogout();

    expect(await listRefs("ref_equipment")).toEqual([]);
    expect(await listRefs("ref_open_tx")).toEqual([]);
    expect(await getMeta("last_snapshot_at")).toBeUndefined();
    expect((await listOutbox("u1")).map((r) => r.op_id)).toEqual([a.op_id]);
    expect((await listJournal("u1")).map((r) => r.op_id)).toEqual([b.op_id]);
    expect(await getDeviceId()).toBe(deviceId);
    expect(await getMeta("device_seq")).toBe(2);
    expect(await getMeta("clock_offset")).toEqual({ ms: 5 });
  });

  it("'remove all data' drops everything including device_id", async () => {
    await enqueueOperation("u1", { body: body(1) });
    const before = await getDeviceId();
    await deleteOfflineDb();
    expect(await countOutbox()).toBe(0);
    expect(await getDeviceId()).not.toBe(before);
    expect(await getMeta("device_seq")).toBeUndefined();
  });
});
