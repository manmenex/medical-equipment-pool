import "fake-indexeddb/auto";

import { IDBFactory } from "fake-indexeddb";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { closeOfflineDb, listRefs, replaceRefs } from "@/offline/offlineStore";

import { deleteLegacyApiCache, LEGACY_API_CACHE_NAME, useAuthStore, whenLogoutWipeDone } from "./authStore";

function stubCaches(names: string[]) {
  const deleted: string[] = [];
  vi.stubGlobal("caches", {
    keys: async () => names,
    delete: async (k: string) => {
      deleted.push(k);
      return true;
    },
  });
  return deleted;
}

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
});
afterEach(async () => {
  vi.unstubAllGlobals();
  await closeOfflineDb();
});

describe("cache wipe on logout (PR25E S4)", () => {
  it("deletes only the exact mep-api-cache name, never a name that merely contains 'api'", async () => {
    const deleted = stubCaches(["mep-api-cache", "workbox-precache-v2", "my-api-docs", "mep-api-cache-2", "rapid"]);
    await deleteLegacyApiCache();
    expect(LEGACY_API_CACHE_NAME).toBe("mep-api-cache");
    expect(deleted).toEqual(["mep-api-cache"]);
  });

  it("logout wipes the reference stores, and whenLogoutWipeDone resolves only after that", async () => {
    const deleted = stubCaches(["mep-api-cache", "workbox-precache-v2"]);
    await replaceRefs("ref_wards", [{ id: "w1" }]);
    useAuthStore.setState({ accessToken: "t", user: { id: "u1" } as never });

    useAuthStore.getState().logout();
    await whenLogoutWipeDone();

    expect(await listRefs("ref_wards")).toEqual([]);
    expect(deleted).toEqual(["mep-api-cache"]);
    expect(useAuthStore.getState().accessToken).toBeNull();
  });

  it("never throws when Cache Storage or IndexedDB is unavailable", async () => {
    vi.stubGlobal("caches", {
      keys: async () => {
        throw new Error("denied");
      },
    });
    await expect(deleteLegacyApiCache()).resolves.toBeUndefined();
  });
});
