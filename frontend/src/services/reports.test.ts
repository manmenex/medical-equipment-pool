import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/services/api";
import { getIssueReport, getOperatorOptions, getReceiveReport } from "@/services/reports";

// Roadmap PR17 Slice 3: proves the report API client calls exactly the
// merged Slice 2 endpoints (GET /reports/receive, GET /reports/issue,
// GET /report-options/operators) with the approved filter params, and
// never GET /transactions or GET /users.

afterEach(() => {
  vi.restoreAllMocks();
});

describe("getReceiveReport", () => {
  it("calls GET /reports/receive with the given params", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { items: [], next_cursor: null, total: 0 } });

    await getReceiveReport({
      business_date_from: "2026-07-01",
      business_date_to: "2026-07-31",
      shift: "day",
      ward_id: "ward-1",
      equipment_category_id: "cat-1",
      equipment_id: "eq-1",
      operator_id: "op-1",
      limit: 25,
      cursor: "cursor-1",
    });

    expect(getSpy).toHaveBeenCalledWith("/reports/receive", {
      params: {
        business_date_from: "2026-07-01",
        business_date_to: "2026-07-31",
        shift: "day",
        ward_id: "ward-1",
        equipment_category_id: "cat-1",
        equipment_id: "eq-1",
        operator_id: "op-1",
        limit: 25,
        cursor: "cursor-1",
      },
    });
  });

  it("never targets GET /transactions", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { items: [], next_cursor: null, total: 0 } });
    await getReceiveReport({});
    expect(getSpy).toHaveBeenCalledWith("/reports/receive", expect.anything());
    expect(getSpy).not.toHaveBeenCalledWith("/transactions", expect.anything());
  });
});

describe("getIssueReport", () => {
  it("calls GET /reports/issue with the given params", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { items: [], next_cursor: null, total: 0 } });

    await getIssueReport({ ward_id: "ward-2", limit: 10, cursor: null });

    expect(getSpy).toHaveBeenCalledWith("/reports/issue", {
      params: { ward_id: "ward-2", limit: 10, cursor: null },
    });
  });

  it("never targets GET /transactions", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { items: [], next_cursor: null, total: 0 } });
    await getIssueReport({});
    expect(getSpy).toHaveBeenCalledWith("/reports/issue", expect.anything());
    expect(getSpy).not.toHaveBeenCalledWith("/transactions", expect.anything());
  });
});

describe("getOperatorOptions", () => {
  it("calls GET /report-options/operators with q/limit/cursor", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { items: [], next_cursor: null, total: 0 } });

    await getOperatorOptions({ q: "สมชาย", limit: 20, cursor: "cursor-1" });

    expect(getSpy).toHaveBeenCalledWith("/report-options/operators", {
      params: { q: "สมชาย", limit: 20, cursor: "cursor-1" },
    });
  });

  it("defaults to an empty params object when called with no arguments", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { items: [], next_cursor: null, total: 0 } });

    await getOperatorOptions();

    expect(getSpy).toHaveBeenCalledWith("/report-options/operators", { params: {} });
  });

  it("never targets GET /users", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { items: [], next_cursor: null, total: 0 } });
    await getOperatorOptions({ q: "test" });
    expect(getSpy).not.toHaveBeenCalledWith("/users", expect.anything());
  });
});
