import "fake-indexeddb/auto";

import { IDBFactory } from "fake-indexeddb";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SnapshotFetch, SnapshotSection } from "@/services/syncClient";
import { useAuthStore } from "@/store/authStore";

import { closeOfflineDb, getMeta, listRefs, wipeOnLogout } from "./offlineStore";
import { resetServerTimeState } from "./serverTime";
import { refreshSnapshot } from "./snapshot";

type Call = { section: SnapshotSection; cursor: string | null; etag: string | null };
const calls: Call[] = [];
let handler: (c: Call) => SnapshotFetch;

vi.mock("@/services/syncClient", async (orig) => ({
  ...(await orig<typeof import("@/services/syncClient")>()),
  fetchSnapshotPage: async (section: SnapshotSection, o: { cursor?: string | null; etag?: string | null }) => {
    const c = { section, cursor: o.cursor ?? null, etag: o.etag ?? null };
    calls.push(c);
    return handler(c);
  },
}));

const page = (
  section: SnapshotSection,
  ids: string[],
  next: string | null,
  etag: string,
  extra: Record<string, unknown> = {},
): SnapshotFetch => ({
  notModified: false,
  etag,
  page: {
    section,
    items: ids.map((id) => ({ id, ...extra })),
    next_cursor: next,
    etag,
    server_time: "2026-10-13T10:00:00Z",
  },
});

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
  resetServerTimeState();
  calls.length = 0;
  useAuthStore.setState({ accessToken: "t", user: { id: "u1" } as never });
});
afterEach(async () => {
  await closeOfflineDb();
  useAuthStore.setState({ accessToken: null, user: null });
});

describe("refreshSnapshot", () => {
  it("pages through every section, upserts by id (equipment may repeat) and records last_snapshot_at", async () => {
    handler = (c) => {
      if (c.section === "equipment" && c.cursor === null) return page("equipment", ["e1", "e2"], "c1", '"a"', { v: 1 });
      if (c.section === "equipment") return page("equipment", ["e2", "e3"], null, '"b"', { v: 2 }); // e2 repeated
      return page(c.section, [`${c.section}-1`], null, `"${c.section}"`);
    };
    const before = Date.now();
    const res = await refreshSnapshot();
    expect(res).toMatchObject({ pagesFetched: 6, pagesNotModified: 0 });
    const eq = await listRefs("ref_equipment");
    expect(eq.map((r) => r.id).sort()).toEqual(["e1", "e2", "e3"]);
    expect(eq.find((r) => r.id === "e2")).toMatchObject({ v: 2 }); // later page wins
    expect((await listRefs("ref_open_tx")).map((r) => r.id)).toEqual(["open_transactions-1"]);
    expect(await getMeta<number>("last_snapshot_at")).toBeGreaterThanOrEqual(before);
  });

  it("sends the remembered ETag, follows a 304 using the stored cursor and ids, and keeps those rows", async () => {
    handler = (c) =>
      c.section === "equipment" && c.cursor === null
        ? page("equipment", ["e1"], "c1", '"a"')
        : c.section === "equipment"
          ? page("equipment", ["e2"], null, '"b"')
          : page(c.section, [], null, `"${c.section}"`);
    await refreshSnapshot();
    calls.length = 0;

    handler = (c) => {
      if (c.section === "equipment" && c.cursor === null) return { notModified: true }; // unchanged first page
      if (c.section === "equipment") return page("equipment", ["e2", "e9"], null, '"b2"'); // changed second page
      return { notModified: true };
    };
    const res = await refreshSnapshot();
    const first = calls.find((c) => c.section === "equipment" && c.cursor === null)!;
    expect(first.etag).toBe('"a"');
    expect(calls.find((c) => c.cursor === "c1")!.etag).toBe('"b"');
    expect(res!.pagesNotModified).toBeGreaterThanOrEqual(1);
    expect((await listRefs("ref_equipment")).map((r) => r.id).sort()).toEqual(["e1", "e2", "e9"]);
  });

  it("prunes rows absent from a completed scan but never on a failed one", async () => {
    handler = (c) => page(c.section, c.section === "wards" ? ["w1", "w2"] : [], null, `"${c.section}1"`);
    await refreshSnapshot();
    handler = (c) => page(c.section, c.section === "wards" ? ["w1"] : [], null, `"${c.section}2"`);
    const ok = await refreshSnapshot();
    expect(ok!.rowsPruned).toBe(1);
    expect((await listRefs("ref_wards")).map((r) => r.id)).toEqual(["w1"]);

    handler = (c) => {
      if (c.section === "wards" && c.cursor === null) return page("wards", ["w1", "w3"], "next", '"x"');
      if (c.section === "wards") throw new Error("network down"); // second page fails
      return page(c.section, [], null, `"${c.section}3"`);
    };
    await expect(refreshSnapshot()).rejects.toThrow("network down");
    // w3 was upserted (harmless), nothing was pruned, and the snapshot time did not advance.
    expect((await listRefs("ref_wards")).map((r) => r.id).sort()).toEqual(["w1", "w3"]);
  });

  it("does not advance last_snapshot_at when a later section fails", async () => {
    handler = (c) => page(c.section, [], null, `"${c.section}"`);
    await refreshSnapshot();
    const t1 = await getMeta<number>("last_snapshot_at");
    await new Promise((r) => setTimeout(r, 5));
    handler = (c) => {
      if (c.section === "locations") throw new Error("boom");
      return page(c.section, [], null, `"${c.section}-2"`);
    };
    await expect(refreshSnapshot()).rejects.toThrow("boom");
    expect(await getMeta<number>("last_snapshot_at")).toBe(t1);
  });

  it("is skipped without a signed-in user and writes nothing after a mid-scan logout", async () => {
    useAuthStore.setState({ accessToken: null, user: null });
    expect(await refreshSnapshot()).toBeNull();
    expect(calls).toHaveLength(0);

    useAuthStore.setState({ accessToken: "t", user: { id: "u1" } as never });
    handler = (c) => {
      if (c.section === "equipment") useAuthStore.setState({ accessToken: null, user: null }); // logout during fetch
      return page(c.section, ["x"], null, '"z"');
    };
    expect(await refreshSnapshot()).toBeNull();
    expect(await listRefs("ref_equipment")).toEqual([]);
    expect(await getMeta("last_snapshot_at")).toBeUndefined();
  });

  it("a logout wipe also forgets page ETags, so the next refresh refetches instead of trusting a 304", async () => {
    handler = (c) => page(c.section, ["r"], null, `"${c.section}"`);
    await refreshSnapshot();
    await wipeOnLogout();
    calls.length = 0;
    handler = (c) => page(c.section, ["r"], null, `"${c.section}"`);
    await refreshSnapshot();
    expect(calls.every((c) => c.etag === null)).toBe(true);
    expect((await listRefs("ref_wards")).map((r) => r.id)).toEqual(["r"]);
  });
});
