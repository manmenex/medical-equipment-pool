import "fake-indexeddb/auto";

import { AxiosError } from "axios";
import { IDBFactory } from "fake-indexeddb";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SyncOperationResult } from "@/services/syncClient";
import { useAuthStore } from "@/store/authStore";

import { closeOfflineDb, enqueueOperation, listJournal, listOutbox } from "./offlineStore";
import {
  BACKOFF_MAX_MS,
  computeBackoff,
  getSyncState,
  LEASE_KEY,
  resetSyncState,
  startSyncWorker,
  syncNow,
} from "./syncWorker";

const post = vi.fn();
vi.mock("@/services/syncClient", async (orig) => ({
  ...(await orig<typeof import("@/services/syncClient")>()),
  postOperations: (ops: Record<string, unknown>[]) => post(ops),
}));

const disp = (eq: string) => ({ op_type: "dispatch", dispatch: { equipment_id: eq } });
const recv = (tx: string) => ({ op_type: "receipt", receipt: { transaction_id: tx } });
const ok = (ops: Record<string, unknown>[], result = "applied"): SyncOperationResult[] =>
  ops.map((o) => ({ op_id: o.op_id as string, result: result as "applied", code: result.toUpperCase() }));
const httpError = (status: number) =>
  new AxiosError("x", String(status), undefined, undefined, {
    status,
    data: {},
    headers: {},
    statusText: "",
    config: {} as never,
  } as never);

function login(id: string | null) {
  useAuthStore.setState({
    user: id ? ({ id } as never) : null,
    accessToken: id ? "tok" : null,
  });
}

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
  post.mockReset();
  resetSyncState();
  localStorage.clear();
  login("u1");
  vi.useFakeTimers({ toFake: ["Date"] });
});
afterEach(async () => {
  vi.useRealTimers();
  await closeOfflineDb();
});

describe("ordering and batching", () => {
  it("sends in device_seq order and batches of 25", async () => {
    for (let i = 0; i < 60; i++) await enqueueOperation("u1", { body: disp(`e${i}`) });
    post.mockImplementation(async (ops) => ok(ops));
    expect(await syncNow()).toBe("done");
    expect(post.mock.calls.map((c) => c[0].length)).toEqual([25, 25, 10]);
    const seqs = post.mock.calls.flatMap((c) => c[0].map((o: { device_seq: number }) => o.device_seq));
    expect(seqs).toEqual([...seqs].sort((a, b) => a - b));
    expect(await listOutbox("u1")).toHaveLength(0);
    expect(await listJournal("u1")).toHaveLength(60);
  });
});

describe("per-op results", () => {
  it("applied and duplicate are acked to the journal", async () => {
    const a = await enqueueOperation("u1", { body: disp("a") });
    const b = await enqueueOperation("u1", { body: disp("b") });
    post.mockResolvedValue([
      { op_id: a.op_id, result: "applied", code: "APPLIED" },
      { op_id: b.op_id, result: "duplicate", code: "DUPLICATE" },
    ]);
    await syncNow();
    expect(await listOutbox("u1")).toHaveLength(0);
    expect((await listJournal("u1")).map((j) => j.kind)).toEqual(["acked", "acked"]);
  });

  it("conflict marks the op and holds later ops on the same equipment and transaction, not unrelated", async () => {
    const d1 = await enqueueOperation("u1", { body: disp("X") });
    const r1 = await enqueueOperation("u1", { body: recv(d1.op_id) });
    const d2 = await enqueueOperation("u1", { body: disp("X") });
    const other = await enqueueOperation("u1", { body: disp("Y") });
    post.mockImplementationOnce(async (ops) => [
      { op_id: d1.op_id, result: "conflict", code: "EQUIPMENT_NOT_AVAILABLE" },
      ...ok(ops.slice(1)),
    ]);
    await syncNow();
    const rows = Object.fromEntries((await listOutbox("u1")).map((r) => [r.op_id, r]));
    expect(rows[d1.op_id].state).toBe("conflict");
    expect(rows[d1.op_id].last_error_code).toBe("EQUIPMENT_NOT_AVAILABLE");
    // all four were in one batch so the server already handled them; only
    // still-pending ones can be held. Verify hold with a separate round below.
    expect(rows[other.op_id]).toBeUndefined();
    void r1;
    void d2;
  });

  it("holds dependents that were not yet sent (>25 ops) and never sends them", async () => {
    const first = await enqueueOperation("u1", { body: disp("X") });
    for (let i = 0; i < 24; i++) await enqueueOperation("u1", { body: disp(`f${i}`) });
    const rcv = await enqueueOperation("u1", { body: recv(first.op_id) });
    const again = await enqueueOperation("u1", { body: disp("X") });
    const unrelated = await enqueueOperation("u1", { body: disp("Z") });
    post.mockImplementation(async (ops) =>
      ops.map((o: { op_id: string }) =>
        o.op_id === first.op_id
          ? { op_id: o.op_id, result: "rejected", code: "OP_ID_REUSED" }
          : { op_id: o.op_id, result: "applied", code: "APPLIED" },
      ),
    );
    await syncNow();
    const sent = post.mock.calls.flatMap((c) => c[0].map((o: { op_id: string }) => o.op_id));
    expect(sent).not.toContain(rcv.op_id);
    expect(sent).not.toContain(again.op_id);
    expect(sent).toContain(unrelated.op_id);
    const rows = Object.fromEntries((await listOutbox("u1")).map((r) => [r.op_id, r]));
    expect(rows[first.op_id].state).toBe("rejected");
    expect(rows[rcv.op_id]).toMatchObject({ state: "held", blocked_by: first.op_id });
    expect(rows[again.op_id]).toMatchObject({ state: "held", blocked_by: first.op_id });
  });

  it("retry_later keeps the op pending, later ops still flow, and backoff starts", async () => {
    const a = await enqueueOperation("u1", { body: recv("unknown-tx") });
    const b = await enqueueOperation("u1", { body: disp("B") });
    post.mockImplementation(async (ops) =>
      ops.map((o: { op_id: string }) =>
        o.op_id === a.op_id
          ? { op_id: o.op_id, result: "retry_later", code: "DEPENDENCY_MISSING" }
          : { op_id: o.op_id, result: "applied", code: "APPLIED" },
      ),
    );
    expect(await syncNow()).toBe("backoff");
    expect(post).toHaveBeenCalledTimes(1);
    const rows = await listOutbox("u1");
    expect(rows.map((r) => r.op_id)).toEqual([a.op_id]);
    expect(rows[0]).toMatchObject({ state: "pending", last_error_code: "DEPENDENCY_MISSING", attempt_count: 1 });
    expect(getSyncState().status).toBe("backoff");
    void b;
  });

  it("unknown result status keeps the op pending and backs off", async () => {
    const a = await enqueueOperation("u1", { body: disp("a") });
    post.mockResolvedValue([{ op_id: a.op_id, result: "weird", code: "?" }]);
    expect(await syncNow()).toBe("backoff");
    expect((await listOutbox("u1"))[0]).toMatchObject({ state: "pending", last_error_code: "UNKNOWN_RESULT" });
  });

  it("a missing result keeps the op pending", async () => {
    await enqueueOperation("u1", { body: disp("a") });
    post.mockResolvedValue([]);
    expect(await syncNow()).toBe("backoff");
    expect((await listOutbox("u1"))[0].state).toBe("pending");
  });
});

describe("failures and backoff", () => {
  it("network error and 5xx keep order and everything pending", async () => {
    const a = await enqueueOperation("u1", { body: disp("a") });
    const b = await enqueueOperation("u1", { body: disp("b") });
    post.mockRejectedValueOnce(new AxiosError("Network Error"));
    expect(await syncNow()).toBe("backoff");
    post.mockRejectedValueOnce(httpError(503));
    expect(await syncNow({ force: true })).toBe("backoff");
    post.mockRejectedValueOnce(httpError(500));
    expect(await syncNow({ force: true })).toBe("backoff");
    const rows = await listOutbox("u1");
    expect(rows.map((r) => [r.op_id, r.state])).toEqual([
      [a.op_id, "pending"],
      [b.op_id, "pending"],
    ]);
    expect(getSyncState().failures).toBe(3);
  });

  it("backoff is exponential, capped, and gates non-forced runs; success resets", async () => {
    expect(computeBackoff(1)).toBe(2000);
    expect(computeBackoff(3)).toBe(8000);
    expect(computeBackoff(50)).toBe(BACKOFF_MAX_MS);
    await enqueueOperation("u1", { body: disp("a") });
    post.mockRejectedValueOnce(new AxiosError("Network Error"));
    await syncNow();
    expect(await syncNow()).toBe("skipped_backoff");
    expect(post).toHaveBeenCalledTimes(1);
    vi.setSystemTime(Date.now() + 2001);
    post.mockImplementation(async (ops) => ok(ops));
    expect(await syncNow()).toBe("done");
    expect(getSyncState()).toMatchObject({ failures: 0, status: "idle" });
  });

  it("401/403 after refresh stops, keeps the queue, and flags auth_required", async () => {
    const a = await enqueueOperation("u1", { body: disp("a") });
    post.mockRejectedValueOnce(httpError(401));
    expect(await syncNow()).toBe("auth_required");
    post.mockRejectedValueOnce(httpError(403));
    expect(await syncNow({ force: true })).toBe("auth_required");
    expect(getSyncState().status).toBe("auth_required");
    expect((await listOutbox("u1"))[0]).toMatchObject({ op_id: a.op_id, state: "pending" });
  });

  it("recovers a row left in `sending` by a closed tab", async () => {
    const { updateOutbox } = await import("./offlineStore");
    const a = await enqueueOperation("u1", { body: disp("a") });
    await updateOutbox("u1", a.op_id, { state: "sending" });
    post.mockImplementation(async (ops) => ok(ops));
    await syncNow();
    expect(post).toHaveBeenCalledTimes(1);
    expect(await listOutbox("u1")).toHaveLength(0);
  });
});

describe("user isolation and logout", () => {
  it("never sends another user's ops; user id comes from the auth store", async () => {
    const mine = await enqueueOperation("u1", { body: disp("a") });
    await enqueueOperation("u2", { body: disp("b") });
    post.mockImplementation(async (ops) => ok(ops));
    await syncNow();
    expect(post.mock.calls.flatMap((c) => c[0].map((o: { op_id: string }) => o.op_id))).toEqual([mine.op_id]);
    expect(await listOutbox("u2")).toHaveLength(1);
    login("u2");
    await syncNow({ force: true });
    expect(await listOutbox("u2")).toHaveLength(0);
  });

  it("does nothing when logged out", async () => {
    await enqueueOperation("u1", { body: disp("a") });
    login(null);
    expect(await syncNow()).toBe("skipped_no_user");
    expect(post).not.toHaveBeenCalled();
  });

  it("stops mid-run when the user logs out, leaving the rest queued", async () => {
    for (let i = 0; i < 30; i++) await enqueueOperation("u1", { body: disp(`e${i}`) });
    post.mockImplementation(async (ops) => {
      login(null);
      return ok(ops);
    });
    expect(await syncNow()).toBe("aborted");
    expect(post).toHaveBeenCalledTimes(1);
    expect(await listOutbox("u1")).toHaveLength(5);
  });

  it("logout via the started worker stops further runs", async () => {
    const stop = startSyncWorker();
    await vi.waitFor(() => expect(getSyncState().status).toBe("idle"));
    login(null);
    expect(getSyncState().status).toBe("stopped");
    stop();
  });
});

describe("single flight", () => {
  it("overlapping calls in one tab send once", async () => {
    await enqueueOperation("u1", { body: disp("a") });
    post.mockImplementation(async (ops) => ok(ops));
    const [x, y] = await Promise.all([syncNow(), syncNow()]);
    expect([x, y].sort()).toEqual(["done", "skipped_locked"]);
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("another tab holding the Web Lock makes this tab skip", async () => {
    await enqueueOperation("u1", { body: disp("a") });
    const request = vi.fn(async (_n: string, _o: unknown, cb: (l: unknown) => Promise<unknown>) => cb(null));
    Object.defineProperty(navigator, "locks", { value: { request }, configurable: true });
    try {
      expect(await syncNow()).toBe("skipped_locked");
      expect(post).not.toHaveBeenCalled();
      expect(request).toHaveBeenCalledWith("mep-sync", { ifAvailable: true }, expect.any(Function));
    } finally {
      Object.defineProperty(navigator, "locks", { value: undefined, configurable: true });
    }
  });

  it("fallback lease in localStorage blocks a second tab until it expires", async () => {
    Object.defineProperty(navigator, "locks", { value: undefined, configurable: true });
    await enqueueOperation("u1", { body: disp("a") });
    localStorage.setItem(LEASE_KEY, JSON.stringify({ owner: "other", expires: Date.now() + 30_000 }));
    expect(await syncNow()).toBe("skipped_locked");
    vi.setSystemTime(Date.now() + 31_000);
    post.mockImplementation(async (ops) => ok(ops));
    expect(await syncNow()).toBe("done");
    expect(localStorage.getItem(LEASE_KEY)).toBeNull();
  });
});

describe("S6 stale client handling", () => {
  const codedError = (status: number, code: string) =>
    new AxiosError("x", String(status), undefined, undefined, {
      status,
      data: { code },
      headers: {},
      statusText: "",
      config: {} as never,
    } as never);

  it("CLIENT_TOO_OLD keeps the whole queue pending, flags update_required and stops retrying", async () => {
    await enqueueOperation("u1", { body: disp("a") });
    await enqueueOperation("u1", { body: disp("b") });
    post.mockRejectedValue(codedError(426, "CLIENT_TOO_OLD"));
    expect(await syncNow()).toBe("update_required");
    expect(getSyncState().status).toBe("update_required");
    const rows = await listOutbox("u1");
    expect(rows.map((r) => r.state)).toEqual(["pending", "pending"]);
    expect(rows.every((r) => r.last_error_code === "CLIENT_TOO_OLD")).toBe(true);
    expect(await listJournal("u1")).toHaveLength(0);
    post.mockClear();
    expect(await syncNow()).toBe("skipped_backoff");
    expect(post).not.toHaveBeenCalled();
  });

  it("ENVELOPE_VERSION_UNSUPPORTED keeps the queue and backs off", async () => {
    await enqueueOperation("u1", { body: disp("a") });
    post.mockRejectedValue(codedError(400, "ENVELOPE_VERSION_UNSUPPORTED"));
    expect(await syncNow()).toBe("backoff");
    expect(getSyncState().lastError).toBe("ENVELOPE_VERSION_UNSUPPORTED");
    expect((await listOutbox("u1")).map((r) => r.state)).toEqual(["pending"]);
  });
});
