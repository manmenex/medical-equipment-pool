import { describe, expect, it } from "vitest";

import { currentShift } from "./shift";

describe("currentShift", () => {
  it("is day from 08:00 up to 20:00 and night otherwise", () => {
    expect(currentShift(new Date(2026, 10, 25, 8, 0))).toBe("day");
    expect(currentShift(new Date(2026, 10, 25, 19, 59))).toBe("day");
    expect(currentShift(new Date(2026, 10, 25, 20, 0))).toBe("night");
    expect(currentShift(new Date(2026, 10, 25, 7, 59))).toBe("night");
    expect(currentShift(new Date(2026, 10, 25, 0, 0))).toBe("night");
  });
});
