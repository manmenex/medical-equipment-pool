import "fake-indexeddb/auto";

import { IDBFactory } from "fake-indexeddb";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { closeOfflineDb, getMeta } from "./offlineStore";
import {
  captureFromResponseHeaders,
  computeClockOffsetMs,
  getClockOffset,
  getLastServerContactAt,
  recordServerTime,
  resetServerTimeState,
} from "./serverTime";

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
  resetServerTimeState();
});
afterEach(async () => {
  await closeOfflineDb();
});

describe("clock offset sign (offset = serverTime - localTime)", () => {
  it("is positive when the device clock is behind the server", () => {
    expect(computeClockOffsetMs(1_000_000, 700_000)).toBe(300_000);
  });
  it("is negative when the device clock is ahead of the server", () => {
    expect(computeClockOffsetMs(700_000, 1_000_000)).toBe(-300_000);
  });
  it("round-trips: local + offset = server", () => {
    const local = 1_700_000_000_123;
    const server = local + 4_321;
    expect(local + computeClockOffsetMs(server, local)).toBe(server);
  });
});

describe("recording server time", () => {
  it("stores offset, measurement time and last contact", async () => {
    const ms = await recordServerTime(10_000, 4_000, { force: true });
    expect(ms).toBe(6_000);
    expect(await getMeta("clock_offset_ms")).toBe(6_000);
    expect(await getMeta("clock_offset_measured_at")).toBe(4_000);
    expect(await getLastServerContactAt()).toBe(4_000);
    expect(await getClockOffset()).toEqual({ ms: 6_000, measuredAt: 4_000 });
  });

  it("falls back to the persisted value after an in-memory reset (reload)", async () => {
    await recordServerTime(10_000, 4_000, { force: true });
    resetServerTimeState();
    expect(await getClockOffset()).toEqual({ ms: 6_000, measuredAt: 4_000 });
  });

  it("captures the HTTP Date header with a half-second centring correction", async () => {
    const date = "Tue, 13 Oct 2026 10:00:00 GMT";
    const local = Date.parse(date) - 60_000; // device 60 s behind
    captureFromResponseHeaders({ date }, local);
    expect(await getClockOffset()).toEqual({ ms: 60_500, measuredAt: local });
  });

  it("a response without a usable Date still counts as server contact, offset untouched", async () => {
    captureFromResponseHeaders({}, 5_000);
    expect(await getLastServerContactAt()).toBe(5_000);
    expect(await getClockOffset()).toBeNull();
  });
});
