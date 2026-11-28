import { describe, expect, it } from "vitest";

import { makeRows, parseSerials, resultsByIndex, rowErrorText } from "@/utils/demoLoanBatch";

// Roadmap PR33 (D14): paste parsing for the demo/loan batch form.
describe("parseSerials", () => {
  it("splits one serial per line, trimming whitespace and dropping empty lines", () => {
    expect(parseSerials("SN-1\n  SN-2  \n\nSN-3\n")).toEqual(["SN-1", "SN-2", "SN-3"]);
  });

  it("handles Windows and old-Mac line endings from pasted Excel columns", () => {
    expect(parseSerials("A1\r\nA2\rA3")).toEqual(["A1", "A2", "A3"]);
  });

  it("uses only the first cell of a pasted multi-column Excel range", () => {
    expect(parseSerials("SN-1\tAcme\t2026\nSN-2\tAcme\t2026")).toEqual(["SN-1", "SN-2"]);
  });

  it("strips the wrapping quotes Excel adds to cells", () => {
    expect(parseSerials('"SN-1"\n"SN-2"')).toEqual(["SN-1", "SN-2"]);
  });

  it("keeps duplicates and original order so the server can flag them per row", () => {
    expect(parseSerials("B\nA\nB")).toEqual(["B", "A", "B"]);
  });

  it("returns an empty list for blank input", () => {
    expect(parseSerials("")).toEqual([]);
    expect(parseSerials("  \n\t\n")).toEqual([]);
  });
});

describe("makeRows", () => {
  it("defaults accessories to present and gives each row a unique key", () => {
    const rows = makeRows(["A", "B"]);
    expect(rows.map((r) => [r.serial, r.has_charger, r.has_clamp])).toEqual([
      ["A", true, true],
      ["B", true, true],
    ]);
    expect(new Set(rows.map((r) => r.key)).size).toBe(2);
  });
});

describe("row error helpers", () => {
  it("maps server error codes to Thai text", () => {
    expect(rowErrorText("duplicate_in_batch")).toContain("ซ้ำ");
    expect(rowErrorText("duplicate_in_db")).toContain("มี Serial นี้ในระบบแล้ว");
    expect(rowErrorText("blank")).toBe("ว่าง");
  });

  it("indexes results by row index", () => {
    const m = resultsByIndex([{ index: 2, serial_number: "X", errors: ["blank"], messages: [] }]);
    expect(m.get(2)?.errors).toEqual(["blank"]);
    expect(m.get(0)).toBeUndefined();
  });
});
