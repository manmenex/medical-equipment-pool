import { describe, expect, it } from "vitest";

import { evaluateStaleness, STALE_THRESHOLD_MS } from "./staleness";

const H = 3_600_000;
const NOW = 100 * H;

describe("staleness (design 9.8, N = 4 h)", () => {
  it("N is four hours", () => {
    expect(STALE_THRESHOLD_MS).toBe(4 * H);
  });
  it("fresh snapshot and recent contact is not stale", () => {
    expect(evaluateStaleness(NOW - 1 * H, NOW - 1 * H, NOW).stale).toBe(false);
  });
  it("exactly 4 h is not yet stale, just over is", () => {
    expect(evaluateStaleness(NOW - 4 * H, NOW, NOW).stale).toBe(false);
    expect(evaluateStaleness(NOW - 4 * H - 1000, NOW, NOW).stale).toBe(true);
  });
  it("an old snapshot alone, or a long offline period alone, triggers it", () => {
    expect(evaluateStaleness(NOW - 5 * H, NOW, NOW).stale).toBe(true);
    expect(evaluateStaleness(NOW, NOW - 5 * H, NOW).stale).toBe(true);
  });
  it("no snapshot at all is stale", () => {
    expect(evaluateStaleness(null, NOW, NOW)).toMatchObject({ stale: true, snapshotAgeS: null });
  });
  it("reports ages in seconds", () => {
    expect(evaluateStaleness(NOW - 2 * H, NOW - 1 * H, NOW)).toEqual({
      snapshotAgeS: 7200,
      offlineForS: 3600,
      stale: false,
    });
  });
});
