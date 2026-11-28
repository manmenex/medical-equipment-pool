import { describe, expect, it } from "vitest";

import { currentBusinessDate, currentShift } from "./shift";

describe("currentBusinessDate", () => {
  it("is the previous calendar day before 08:00 (shift-start anchored)", () => {
    expect(currentBusinessDate(new Date(2026, 10, 25, 7, 59))).toBe("2026-11-24");
    expect(currentBusinessDate(new Date(2026, 10, 25, 8, 0))).toBe("2026-11-25");
    expect(currentBusinessDate(new Date(2026, 10, 25, 23, 0))).toBe("2026-11-25");
    expect(currentBusinessDate(new Date(2026, 0, 1, 3, 0))).toBe("2025-12-31");
  });
});

describe("currentShift", () => {
  it("is day from 08:00 up to 20:00 and night otherwise", () => {
    expect(currentShift(new Date(2026, 10, 25, 8, 0))).toBe("day");
    expect(currentShift(new Date(2026, 10, 25, 19, 59))).toBe("day");
    expect(currentShift(new Date(2026, 10, 25, 20, 0))).toBe("night");
    expect(currentShift(new Date(2026, 10, 25, 7, 59))).toBe("night");
    expect(currentShift(new Date(2026, 10, 25, 0, 0))).toBe("night");
  });
});
