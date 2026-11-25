import "fake-indexeddb/auto";

import { AxiosError } from "axios";
import { IDBFactory } from "fake-indexeddb";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "@/store/authStore";

import { decryptHn, encryptHn, envelopeForSend, hnEncryptionAvailable } from "./hnVault";
import { enqueueOfflineDispatch, LocalOpError } from "./localOps";
import {
  ackOperation,
  closeOfflineDb,
  discardOperation,
  listJournal,
  listOutbox,
  replaceRefs,
  setMeta,
  updateOutbox,
  wipeOnLogout,
  openOfflineDb,
} from "./offlineStore";
import { recordServerTime, resetServerTimeState } from "./serverTime";
import { resetStaleAcknowledgement } from "./staleness";
import { getSyncState, resetSyncState, syncNow } from "./syncWorker";

// Roadmap PR29 (D1): the offline queue is an HN surface -- encrypted at rest on
// the device (AES-GCM, non-extractable per-device key), cleared once the server
// answers, never logged.

const HN = "HN-8842/66";

const post = vi.fn();
// enqueueOfflineDispatch fires requestSync(); these tests drive syncNow() by hand.
vi.mock("./syncWorker", async (orig) => ({
  ...(await orig<typeof import("./syncWorker")>()),
  requestSync: () => undefined,
}));
vi.mock("@/services/syncClient", async (orig) => ({
  ...(await orig<typeof import("@/services/syncClient")>()),
  postOperations: (ops: Record<string, unknown>[]) => post(ops),
}));

async function dumpAllStores(): Promise<string> {
  const db = await openOfflineDb();
  const parts: string[] = [];
  for (const name of [...db.objectStoreNames]) {
    for (const row of await db.getAll(name as never)) {
      // CryptoKey objects serialise to {} -- the point is that no plaintext shows up.
      parts.push(JSON.stringify(row));
    }
  }
  return parts.join("\n");
}

async function seed() {
  await replaceRefs("ref_equipment", [
    { id: "e1", bcm_code: "BCM001", equipment_name: "Pump", category_name: "Pumps", status: "available_at_pool" },
  ]);
  await replaceRefs("ref_wards", [{ id: "w1", name: "Ward A" }]);
  await setMeta("last_snapshot_at", Date.now() - 60_000);
  await recordServerTime(Date.now() + 5_000, Date.now(), { force: true });
}

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
  resetServerTimeState();
  resetStaleAcknowledgement();
  resetSyncState();
  post.mockReset();
  useAuthStore.setState({ accessToken: "t", user: { id: "u1" } as never });
});
afterEach(async () => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  await closeOfflineDb();
  useAuthStore.setState({ accessToken: null, user: null });
});

describe("hnVault", () => {
  it("round-trips an HN and the ciphertext does not contain it", async () => {
    expect(hnEncryptionAvailable()).toBe(true);
    const blob = await encryptHn(HN);
    expect(JSON.stringify(blob)).not.toContain(HN);
    expect(blob.v).toBe(1);
    expect(await decryptHn(blob)).toBe(HN);
    // random IV: same value, different ciphertext
    expect((await encryptHn(HN)).ct).not.toBe(blob.ct);
  });

  it("uses one non-extractable device key that can never be exported", async () => {
    await encryptHn(HN);
    const db = await openOfflineDb();
    const key = (await db.get("meta", "hn_device_key"))?.value as CryptoKey;
    expect(key.extractable).toBe(false);
    await expect(globalThis.crypto.subtle.exportKey("raw", key)).rejects.toBeDefined();
    const again = (await db.get("meta", "hn_device_key"))?.value as CryptoKey;
    await encryptHn("12345");
    expect(((await db.get("meta", "hn_device_key"))?.value as CryptoKey).algorithm).toEqual(again.algorithm);
  });

  it("returns null (not a throw) when the device key is gone or the data is damaged", async () => {
    const blob = await encryptHn(HN);
    expect(await decryptHn({ ...blob, ct: blob.ct.slice(2) + "AA" })).toBeNull();
    globalThis.indexedDB = new IDBFactory(); // a different profile/device: no key
    await closeOfflineDb();
    expect(await decryptHn(blob)).toBeNull();
  });
});

describe("offline dispatch with HN", () => {
  it("stores only an encrypted HN on the row, never in the envelope, and nothing in clear anywhere", async () => {
    await seed();
    const rec = await enqueueOfflineDispatch({ equipment_id: "e1", ward_id: "w1", hn: HN });
    expect(rec.hn_enc).toBeDefined();
    expect(JSON.stringify(rec.envelope)).not.toContain(HN);
    expect((rec.envelope as { dispatch: Record<string, unknown> }).dispatch).not.toHaveProperty("hn");
    expect(await dumpAllStores()).not.toContain(HN);
    expect(await dumpAllStores()).not.toContain("8842");
  });

  it("an op without HN has no hn_enc", async () => {
    await seed();
    const rec = await enqueueOfflineDispatch({ equipment_id: "e1", ward_id: "w1", hn: "   " });
    expect(rec.hn_enc).toBeUndefined();
  });

  it("refuses to queue an HN (and queues nothing) when WebCrypto is unavailable", async () => {
    await seed();
    vi.stubGlobal("crypto", { randomUUID: () => "00000000-0000-4000-8000-000000000000" });
    expect(hnEncryptionAvailable()).toBe(false);
    await expect(enqueueOfflineDispatch({ equipment_id: "e1", ward_id: "w1", hn: HN })).rejects.toMatchObject({
      code: "HN_UNAVAILABLE",
    });
    await expect(enqueueOfflineDispatch({ equipment_id: "e1", ward_id: "w1", hn: HN })).rejects.toBeInstanceOf(LocalOpError);
    expect(await listOutbox("u1")).toHaveLength(0);
    expect(await dumpAllStores()).not.toContain(HN);
  });

  it("envelopeForSend decrypts the HN into the request body only", async () => {
    await seed();
    const rec = await enqueueOfflineDispatch({ equipment_id: "e1", ward_id: "w1", hn: HN });
    const out = await envelopeForSend(rec);
    expect((out as { dispatch: { hn: string } }).dispatch.hn).toBe(HN);
    expect(JSON.stringify(rec.envelope)).not.toContain(HN); // stored envelope untouched
    const damaged = { ...rec, hn_enc: { ...rec.hn_enc!, ct: "AAAA" } };
    expect(await envelopeForSend(damaged)).toBe(rec.envelope); // dispatch still goes, without HN
  });
});

describe("sync worker and HN lifecycle", () => {
  it("sends the HN in the request body, then removes every trace of it once the server acks", async () => {
    await seed();
    await enqueueOfflineDispatch({ equipment_id: "e1", ward_id: "w1", hn: HN });
    let sent: Array<{ op_id: string; dispatch: { hn?: string } }> = [];
    post.mockImplementation(async (ops) => {
      sent = ops;
      return ops.map((o: { op_id: string }) => ({ op_id: o.op_id, result: "applied", code: "APPLIED" }));
    });
    expect(await syncNow({ force: true })).toBe("done");
    expect(sent[0].dispatch.hn).toBe(HN);
    expect(await listOutbox("u1")).toHaveLength(0);
    const journal = await listJournal("u1");
    expect(journal).toHaveLength(1);
    expect(JSON.stringify(journal)).not.toContain(HN);
    expect(journal[0]).not.toHaveProperty("hn_enc");
    expect(await dumpAllStores()).not.toContain(HN);
  });

  it("a network failure keeps the encrypted HN so the retry still carries it", async () => {
    await seed();
    await enqueueOfflineDispatch({ equipment_id: "e1", ward_id: "w1", hn: HN });
    post.mockRejectedValueOnce(new AxiosError("net", "ERR_NETWORK"));
    expect(await syncNow({ force: true })).toBe("backoff");
    const [row] = await listOutbox("u1");
    expect(row.state).toBe("pending");
    expect(row.hn_enc).toBeDefined();
    post.mockImplementationOnce(async (ops) => {
      expect(ops[0].dispatch.hn).toBe(HN);
      return ops.map((o: { op_id: string }) => ({ op_id: o.op_id, result: "applied", code: "APPLIED" }));
    });
    expect(await syncNow({ force: true })).toBe("done");
    expect(post).toHaveBeenCalledTimes(2);
  });

  it.each(["conflict", "rejected"] as const)("a %s answer clears the HN from the device", async (result) => {
    await seed();
    await enqueueOfflineDispatch({ equipment_id: "e1", ward_id: "w1", hn: HN });
    post.mockImplementation(async (ops) =>
      ops.map((o: { op_id: string }) => ({ op_id: o.op_id, result, code: "X" })),
    );
    await syncNow({ force: true });
    const [row] = await listOutbox("u1");
    expect(row.state).toBe(result);
    expect(row.hn_enc).toBeUndefined();
    expect(await dumpAllStores()).not.toContain(HN);
  });

  it("discarding a queued op and acking through the store both drop the HN", async () => {
    await seed();
    const a = await enqueueOfflineDispatch({ equipment_id: "e1", ward_id: "w1", hn: HN });
    await discardOperation("u1", a.op_id);
    const journal = await listJournal("u1");
    expect(journal[0].kind).toBe("discarded");
    expect(journal[0]).not.toHaveProperty("hn_enc");
    const b = await enqueueOfflineDispatch({ equipment_id: "e1", ward_id: "w1", hn: HN });
    await ackOperation("u1", b.op_id, { result: "applied" });
    expect(await dumpAllStores()).not.toContain(HN);
  });

  it("an updateOutbox to a non-terminal state keeps the encrypted HN; logout wipe keeps the device key", async () => {
    await seed();
    const rec = await enqueueOfflineDispatch({ equipment_id: "e1", ward_id: "w1", hn: HN });
    await updateOutbox("u1", rec.op_id, { state: "held", blocked_by: "x" });
    expect((await listOutbox("u1"))[0].hn_enc).toBeDefined();
    await wipeOnLogout();
    const db = await openOfflineDb();
    expect(await db.get("meta", "hn_device_key")).toBeDefined();
    expect(await decryptHn((await listOutbox("u1"))[0].hn_enc!)).toBe(HN);
  });

  it("never writes an HN to the console", async () => {
    await seed();
    const spies = (["log", "info", "warn", "error", "debug"] as const).map((m) => vi.spyOn(console, m).mockImplementation(() => {}));
    await enqueueOfflineDispatch({ equipment_id: "e1", ward_id: "w1", hn: HN });
    post.mockRejectedValueOnce(new AxiosError("net", "ERR_NETWORK"));
    await syncNow({ force: true });
    for (const s of spies) expect(JSON.stringify(s.mock.calls)).not.toContain(HN);
    expect(getSyncState().lastError ?? "").not.toContain(HN);
  });
});
