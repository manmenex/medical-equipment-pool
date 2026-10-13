import "fake-indexeddb/auto";

import { IDBFactory } from "fake-indexeddb";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "@/store/authStore";

import {
  DUPLICATE_LOCAL_MESSAGE,
  effectiveCachedEquipment,
  enqueueOfflineDispatch,
  enqueueOfflineReceipt,
  listReceiptCandidates,
  LocalOpError,
  searchCachedBcm,
  stripBcmPrefix,
} from "./localOps";
import { closeOfflineDb, enqueueOperation, listOutbox, replaceRefs, setMeta } from "./offlineStore";
import { recordServerTime, resetServerTimeState } from "./serverTime";
import { acknowledgeStaleness, resetStaleAcknowledgement } from "./staleness";

const requestSync = vi.fn();
vi.mock("./syncWorker", () => ({ requestSync: () => requestSync() }));

const EQ = [
  { id: "e1", bcm_code: "BCM001", equipment_name: "Pump", category_name: "Pumps", status: "available_at_pool" },
  { id: "e2", bcm_code: "BCM0012", equipment_name: "Monitor", category_name: "Mon", status: "available_at_pool" },
  { id: "e3", bcm_code: "BCM777", equipment_name: "Vent", category_name: "V", status: "issued_to_ward" },
  { id: "e4", bcm_code: "BCM900", equipment_name: "Broken", category_name: "B", status: "unavailable_defective" },
];

async function seed({ snapshotAgeMs = 60_000 }: { snapshotAgeMs?: number } = {}) {
  await replaceRefs("ref_equipment", EQ);
  await replaceRefs("ref_wards", [{ id: "w1", name: "Ward A", phone: "111" }]);
  await replaceRefs("ref_open_tx", [{ id: "t3", equipment_id: "e3", ward_id: "w1", borrowed_at: "2026-10-13T01:00:00Z" }]);
  await setMeta("last_snapshot_at", Date.now() - snapshotAgeMs);
  await recordServerTime(Date.now() + 5_000, Date.now(), { force: true });
}

function login(id = "u1") {
  useAuthStore.setState({ accessToken: "t", user: { id } as never });
}

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
  resetServerTimeState();
  resetStaleAcknowledgement();
  requestSync.mockReset();
  login();
});
afterEach(async () => {
  await closeOfflineDb();
  useAuthStore.setState({ accessToken: null, user: null });
});

describe("BCM search over the cache (D1)", () => {
  it("strips the BCM prefix like the server and matches bcm_code only", async () => {
    await seed();
    expect(stripBcmPrefix("  bcm 001 ")).toBe("001");
    expect((await searchCachedBcm("bcm001")).map((s) => s.bcm_code)).toEqual(["BCM001", "BCM0012"]); // exact first
    expect((await searchCachedBcm("77")).map((s) => s.bcm_code)).toEqual(["BCM777"]);
    expect(await searchCachedBcm("Pump")).toEqual([]); // names are not searched
    expect(await searchCachedBcm("  ")).toEqual([]);
  });

  it("suggestions expose only id and bcm_code", async () => {
    await seed();
    expect(Object.keys((await searchCachedBcm("001"))[0]).sort()).toEqual(["bcm_code", "id"]);
  });
});

describe("offline dispatch", () => {
  it("enqueues the exact dispatch envelope with operator from the auth store, local time and offset", async () => {
    await seed();
    const before = Date.now();
    const rec = await enqueueOfflineDispatch({
      equipment_id: "e1",
      ward_id: "w1",
      dispatch_type: "routine_round",
      routine_round: "11:00",
      phone_number: "111",
      notes: "n",
    });
    const env = rec.envelope as Record<string, unknown>;
    expect(env).toMatchObject({
      user_id: "u1",
      op_type: "dispatch",
      dispatch: { equipment_id: "e1", ward_id: "w1", dispatch_type: "routine_round", routine_round: "11:00", phone_number: "111", notes: "n" },
      op_id: rec.op_id,
      device_seq: 1,
    });
    expect(Date.parse(env.occurred_at_local as string)).toBeGreaterThanOrEqual(before);
    expect(env.clock_offset_ms).toBeGreaterThanOrEqual(4_900); // server ahead by ~5 s => positive
    expect(env.clock_offset_ms).toBeLessThanOrEqual(5_100);
    expect(env).not.toHaveProperty("receipt");
    // no identifiers other than ids/BCM-free envelope, no status, no stale fields on the wire
    expect(JSON.stringify(env)).not.toMatch(/asset|item_no|qr|status|stale|snapshot_age/i);
    expect(rec.stale_context).toBe(false);
    expect((await listOutbox("u1")).map((r) => r.op_id)).toEqual([rec.op_id]);
    expect(requestSync).toHaveBeenCalledTimes(1);
  });

  it("on_demand carries no routine_round and omits empty optional fields", async () => {
    await seed();
    const rec = await enqueueOfflineDispatch({ equipment_id: "e1", ward_id: "w1", dispatch_type: "on_demand", routine_round: "06:00" });
    expect((rec.envelope as { dispatch: object }).dispatch).toEqual({ equipment_id: "e1", ward_id: "w1", dispatch_type: "on_demand" });
  });

  it("uses the signed-in user, and refuses without one", async () => {
    await seed();
    login("u2");
    const rec = await enqueueOfflineDispatch({ equipment_id: "e1", ward_id: "w1", dispatch_type: "on_demand" });
    expect(rec.user_id).toBe("u2");
    expect((rec.envelope as { user_id: string }).user_id).toBe("u2");
    useAuthStore.setState({ accessToken: null, user: null });
    await expect(enqueueOfflineDispatch({ equipment_id: "e2", ward_id: "w1", dispatch_type: "on_demand" })).rejects.toMatchObject({ code: "NO_USER" });
  });

  it("refuses equipment that is not available per the cache", async () => {
    await seed();
    await expect(enqueueOfflineDispatch({ equipment_id: "e3", ward_id: "w1", dispatch_type: "on_demand" })).rejects.toMatchObject({ code: "NOT_AVAILABLE" });
    await expect(enqueueOfflineDispatch({ equipment_id: "e4", ward_id: "w1", dispatch_type: "on_demand" })).rejects.toMatchObject({ code: "NOT_AVAILABLE" });
    await expect(enqueueOfflineDispatch({ equipment_id: "nope", ward_id: "w1", dispatch_type: "on_demand" })).rejects.toMatchObject({ code: "NOT_FOUND" });
  });

  it("local double-entry guard blocks a second dispatch of the same equipment with a generic message", async () => {
    await seed();
    await enqueueOfflineDispatch({ equipment_id: "e1", ward_id: "w1", dispatch_type: "on_demand" });
    const err = await enqueueOfflineDispatch({ equipment_id: "e1", ward_id: "w1", dispatch_type: "on_demand" }).catch((e) => e);
    expect(err).toBeInstanceOf(LocalOpError);
    expect(err.code).toBe("DUPLICATE_LOCAL");
    expect(err.message).toBe(DUPLICATE_LOCAL_MESSAGE);
    expect(await listOutbox("u1")).toHaveLength(1);
  });

  it("the guard also sees another user's unsent entry but reveals nothing about it", async () => {
    await seed();
    login("u1");
    await enqueueOfflineDispatch({ equipment_id: "e1", ward_id: "w1", dispatch_type: "on_demand" });
    login("u2");
    const err = await enqueueOfflineDispatch({ equipment_id: "e1", ward_id: "w1", dispatch_type: "on_demand", notes: "x" }).catch((e) => e);
    expect(err.code).toBe("DUPLICATE_LOCAL");
    expect(err.message).toBe(DUPLICATE_LOCAL_MESSAGE);
    expect(err.message).not.toMatch(/u1|BCM|Ward/);
    expect(await listOutbox("u2")).toEqual([]);
  });

  it("a queued receipt of the open transaction makes the equipment dispatchable again locally", async () => {
    await seed();
    await enqueueOfflineReceipt({ transaction_id: "t3", receipt_outcome: "usable" });
    expect((await effectiveCachedEquipment("e3")).equipment.status).toBe("available_at_pool");
    const rec = await enqueueOfflineDispatch({ equipment_id: "e3", ward_id: "w1", dispatch_type: "on_demand" });
    expect(rec.op_id).toBeTruthy();
  });
});

describe("offline receipt", () => {
  it("enqueues a receipt addressed by transaction_id only, with outcome and operator", async () => {
    await seed();
    const rec = await enqueueOfflineReceipt({ transaction_id: "t3", receipt_outcome: "defective", notes: "cracked" });
    const env = rec.envelope as Record<string, unknown>;
    expect(env).toMatchObject({ user_id: "u1", op_type: "receipt", receipt: { transaction_id: "t3", receipt_outcome: "defective", notes: "cracked" } });
    expect(env).not.toHaveProperty("dispatch");
    expect(Object.keys(env.receipt as object).sort()).toEqual(["notes", "receipt_outcome", "transaction_id"]);
    expect(requestSync).toHaveBeenCalledTimes(1);
  });

  it("blocks a second unsent receipt for the same transaction (generic message)", async () => {
    await seed();
    await enqueueOfflineReceipt({ transaction_id: "t3", receipt_outcome: "usable" });
    const err = await enqueueOfflineReceipt({ transaction_id: "t3", receipt_outcome: "defective" }).catch((e) => e);
    expect(err.code).toBe("DUPLICATE_LOCAL");
    expect(err.message).toBe(DUPLICATE_LOCAL_MESSAGE);
  });

  it("candidates = snapshot open transactions + this user's own offline dispatches (receivable by their op_id)", async () => {
    await seed();
    const d = await enqueueOfflineDispatch({ equipment_id: "e1", ward_id: "w1", dispatch_type: "on_demand" });
    const list = await listReceiptCandidates();
    expect(list.map((c) => [c.transaction_id, c.source, c.bcm_code, c.ward_name])).toEqual([
      [d.op_id, "local", "BCM001", "Ward A"],
      ["t3", "snapshot", "BCM777", "Ward A"],
    ]);
    // receiving the local dispatch references its op_id as transaction_id
    const r = await enqueueOfflineReceipt({ transaction_id: d.op_id, receipt_outcome: "usable" });
    expect((r.envelope as { receipt: { transaction_id: string } }).receipt.transaction_id).toBe(d.op_id);
    expect((await listReceiptCandidates()).map((c) => c.transaction_id)).toEqual(["t3"]);
  });

  it("does not list another user's unsent offline dispatches", async () => {
    await seed();
    login("u1");
    await enqueueOfflineDispatch({ equipment_id: "e1", ward_id: "w1", dispatch_type: "on_demand" });
    login("u2");
    expect((await listReceiptCandidates()).map((c) => c.transaction_id)).toEqual(["t3"]);
  });

  it("candidates carry no Asset Number / Item No", async () => {
    await seed();
    const keys = Object.keys((await listReceiptCandidates())[0]).sort();
    expect(keys).toEqual(["borrowed_at", "bcm_code", "equipment_id", "equipment_name", "source", "transaction_id", "ward_id", "ward_name"].sort());
  });
});

describe("staleness acknowledgement and stale_context (design 9.8)", () => {
  it("refuses to enqueue while the device is stale and unacknowledged", async () => {
    await seed({ snapshotAgeMs: 5 * 3_600_000 });
    await expect(enqueueOfflineDispatch({ equipment_id: "e1", ward_id: "w1", dispatch_type: "on_demand" })).rejects.toMatchObject({ code: "STALE_NOT_ACKNOWLEDGED" });
    await expect(enqueueOfflineReceipt({ transaction_id: "t3", receipt_outcome: "usable" })).rejects.toMatchObject({ code: "STALE_NOT_ACKNOWLEDGED" });
    expect(await listOutbox("u1")).toEqual([]);
  });

  it("after acknowledgement, enqueues marked stale_context with snapshot_age_s (local only, not in the envelope)", async () => {
    await seed({ snapshotAgeMs: 5 * 3_600_000 });
    acknowledgeStaleness();
    const rec = await enqueueOfflineDispatch({ equipment_id: "e1", ward_id: "w1", dispatch_type: "on_demand" });
    expect(rec.stale_context).toBe(true);
    expect(rec.snapshot_age_s).toBeGreaterThanOrEqual(5 * 3600);
    expect(rec.envelope).not.toHaveProperty("stale_context");
    expect(rec.envelope).not.toHaveProperty("snapshot_age_s");
    const r2 = await enqueueOfflineReceipt({ transaction_id: "t3", receipt_outcome: "usable" });
    expect(r2.stale_context).toBe(true);
  });

  it("a fresh device is not marked stale and needs no acknowledgement", async () => {
    await seed();
    const rec = await enqueueOfflineDispatch({ equipment_id: "e1", ward_id: "w1", dispatch_type: "on_demand" });
    expect(rec.stale_context).toBe(false);
  });

  it("a pre-existing outbox row (no local flags) is unaffected by the new fields", async () => {
    const rec = await enqueueOperation("u1", { body: { op_type: "dispatch" } });
    expect(rec).not.toHaveProperty("stale_context");
  });
});
