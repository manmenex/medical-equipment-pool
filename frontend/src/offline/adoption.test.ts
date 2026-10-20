import "fake-indexeddb/auto";

import { IDBFactory } from "fake-indexeddb";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SyncOperationResult } from "@/services/syncClient";
import { useAuthStore } from "@/store/authStore";

import { adoptOps, listAdoptableGroups, reauthenticate } from "./adoption";
import { closeOfflineDb, enqueueOperation, listJournal, listOutbox, rememberUserName } from "./offlineStore";

const post = vi.fn();
vi.mock("@/services/syncClient", async (orig) => ({
  ...(await orig<typeof import("@/services/syncClient")>()),
  postOperations: (ops: Record<string, unknown>[]) => post(ops),
}));
const loginMock = vi.fn();
vi.mock("@/services/auth", () => ({ login: (...a: unknown[]) => loginMock(...a) }));

const disp = (eq: string, user = "orig") => ({ user_id: user, op_type: "dispatch", occurred_at_local: "2026-10-13T08:00:00Z", dispatch: { equipment_id: eq } });
const res = (ops: Record<string, unknown>[], result: string, code = result.toUpperCase()): SyncOperationResult[] =>
  ops.map((o) => ({ op_id: o.op_id as string, result: result as "applied", code }));

beforeEach(async () => {
  globalThis.indexedDB = new IDBFactory();
  post.mockReset();
  loginMock.mockReset();
  useAuthStore.setState({
    user: { id: "adopter", employee_code: "A001", full_name: "Adopter" } as never,
    accessToken: "tok",
  });
  await enqueueOperation("orig", { body: disp("e1") });
  await enqueueOperation("orig", { body: disp("e2") });
  await enqueueOperation("adopter", { body: disp("e3", "adopter") });
  await rememberUserName("orig", "สมชาย");
});
afterEach(async () => {
  await closeOfflineDb();
});

describe("adoption", () => {
  it("lists only other users' rows, counted per user with cached name", async () => {
    const groups = await listAdoptableGroups("adopter");
    expect(groups).toHaveLength(1);
    expect(groups[0]).toMatchObject({ user_id: "orig", name: "สมชาย", count: 2 });
    expect(Object.keys(groups[0].ops[0]).sort()).toEqual(["bcm_code", "occurred_at", "op_id", "op_type", "original_user_id"]);
  });

  it("sends with adopt + original_user_id and acks into the original user's journal", async () => {
    post.mockImplementation(async (ops) => res(ops, "applied"));
    const out = await adoptOps("adopter", new Set(["orig"]), () => true);
    expect(out.applied).toBe(2);
    const sent = post.mock.calls[0][0] as Record<string, unknown>[];
    expect(sent.every((o) => o.adopt === true && o.original_user_id === "orig" && o.user_id === "orig")).toBe(true);
    expect(await listOutbox("orig")).toHaveLength(0);
    expect(await listJournal("orig")).toHaveLength(2);
    expect(await listOutbox("adopter")).toHaveLength(1); // own row untouched
  });

  it("does not send when offline", async () => {
    const out = await adoptOps("adopter", new Set(["orig"]), () => false);
    expect(out.error).toBe("OFFLINE");
    expect(post).not.toHaveBeenCalled();
  });

  it("conflict keeps the row locally as conflict and counts it", async () => {
    post.mockImplementation(async (ops) => res(ops, "conflict", "EQUIPMENT_NOT_AVAILABLE"));
    const out = await adoptOps("adopter", new Set(["orig"]), () => true);
    expect(out.conflict).toBe(2);
    expect((await listOutbox("orig")).every((r) => r.state === "conflict")).toBe(true);
  });

  it("ADOPT_REAUTH_REQUIRED leaves everything pending and flags it", async () => {
    post.mockImplementation(async (ops) => res(ops, "rejected", "ADOPT_REAUTH_REQUIRED"));
    const out = await adoptOps("adopter", new Set(["orig"]), () => true);
    expect(out.reauth_required).toBe(true);
    expect(out.left_pending).toBe(2);
    expect((await listOutbox("orig")).every((r) => r.state === "pending")).toBe(true);
  });

  it("network failure leaves rows pending and reports the error", async () => {
    post.mockRejectedValue(new Error("down"));
    const out = await adoptOps("adopter", new Set(["orig"]), () => true);
    expect(out.error).toBe("NETWORK");
    expect((await listOutbox("orig")).every((r) => r.state === "pending")).toBe(true);
  });

  it("only adopts the selected users", async () => {
    const out = await adoptOps("adopter", new Set(["someone-else"]), () => true);
    expect(out.applied).toBe(0);
    expect(post).not.toHaveBeenCalled();
  });

  it("reauthenticate logs in with the current user's code and replaces the token", async () => {
    loginMock.mockResolvedValue({ access_token: "fresh", expires_in: 900 });
    await reauthenticate("pw");
    expect(loginMock).toHaveBeenCalledWith("A001", "pw");
    expect(useAuthStore.getState().accessToken).toBe("fresh");
  });

  it("reauthenticate failure keeps the old token", async () => {
    loginMock.mockRejectedValue(new Error("401"));
    await expect(reauthenticate("bad")).rejects.toThrow();
    expect(useAuthStore.getState().accessToken).toBe("tok");
  });
});
