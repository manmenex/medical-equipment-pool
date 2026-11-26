import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// Global table styling must never leak into print views (.print-table):
// printing stays black-on-white regardless of the active theme.
describe("index.css print isolation", () => {
  const css = readFileSync(`${__dirname}/index.css`, "utf8");
  it("scopes global table rules away from .print-table", () => {
    expect(css).not.toMatch(/(^|\n)\s*(thead|tbody)\b/);
    expect(css).toMatch(/table:not\(\.print-table\) thead th/);
    expect(css).toMatch(/table:not\(\.print-table\) tbody tr/);
  });
  it("uses a dedicated field-group class, not a broad div.border selector", () => {
    expect(css).not.toMatch(/div\.border/);
    expect(css).toMatch(/\.field-group/);
  });
});
