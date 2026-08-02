import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/services/api";
import { buildPrintDataFilters, getReportPrintData } from "@/services/printReports";

// Roadmap PR18C (docs/design/PR18_PRINTING_EXPORT_PLAN.md §6.2/§9): proves
// the print client calls exactly the merged PR18B endpoint
// (GET /reports/{report_id}/print-data) with the filters it was given -- no
// `limit`/`cursor`. The explicit per-report-identity whitelist that decides
// *which* filters those are lives in `buildPrintDataFilters` (review
// 4837997016, H2), tested separately below.

afterEach(() => {
  vi.restoreAllMocks();
});

describe("getReportPrintData", () => {
  it("calls GET /reports/{report_id}/print-data with the given filters", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({
      data: { metadata: {}, columns: [], rows: [] },
    });

    await getReportPrintData("receive-report", { ward_id: "ward-1", shift: "day" });

    expect(getSpy).toHaveBeenCalledWith("/reports/receive-report/print-data", {
      params: { ward_id: "ward-1", shift: "day" },
    });
  });

  it("supports every report identity in the route path", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { metadata: {}, columns: [], rows: [] } });

    await getReportPrintData("issue-report", {});
    await getReportPrintData("equipment-verify-checklist", {});

    expect(getSpy).toHaveBeenCalledWith("/reports/issue-report/print-data", { params: {} });
    expect(getSpy).toHaveBeenCalledWith("/reports/equipment-verify-checklist/print-data", { params: {} });
  });

  it("never sends limit or cursor -- print-data always returns the complete bounded result set", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { metadata: {}, columns: [], rows: [] } });

    await getReportPrintData("receive-report", { ward_id: "ward-1" });

    const [, config] = getSpy.mock.calls[0];
    expect((config as { params: Record<string, unknown> }).params).not.toHaveProperty("limit");
    expect((config as { params: Record<string, unknown> }).params).not.toHaveProperty("cursor");
  });

  it("never targets GET /transactions or another endpoint", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { metadata: {}, columns: [], rows: [] } });
    await getReportPrintData("receive-report", {});
    expect(getSpy).not.toHaveBeenCalledWith("/transactions", expect.anything());
  });
});

describe("buildPrintDataFilters", () => {
  it("forwards only the whitelisted keys for receive-report", () => {
    const params = new URLSearchParams({
      business_date_from: "2026-07-01",
      shift: "day",
      ward_id: "ward-1",
    });
    expect(buildPrintDataFilters("receive-report", params)).toEqual({
      business_date_from: "2026-07-01",
      shift: "day",
      ward_id: "ward-1",
    });
  });

  it("includes dispatch_type/routine_round only for issue-report", () => {
    const params = new URLSearchParams({ dispatch_type: "on_demand", routine_round: "06:00" });
    expect(buildPrintDataFilters("issue-report", params)).toEqual({
      dispatch_type: "on_demand",
      routine_round: "06:00",
    });
    // Neither key is in receive-report's whitelist, even though both are
    // present on the URL.
    expect(buildPrintDataFilters("receive-report", params)).toEqual({});
  });

  it("restricts equipment-verify-checklist to its own three filters, dropping report-family-specific ones", () => {
    const params = new URLSearchParams({
      status: "available_at_pool",
      equipment_category_id: "cat-1",
      department_id: "dept-1",
      // Receive/Issue-only filters that must never leak through:
      business_date_from: "2026-07-01",
      shift: "day",
      ward_id: "ward-1",
    });
    expect(buildPrintDataFilters("equipment-verify-checklist", params)).toEqual({
      status: "available_at_pool",
      equipment_category_id: "cat-1",
      department_id: "dept-1",
    });
  });

  // Roadmap PR18C review 4837997016 (H2): the exact bug this whitelist
  // fixes -- a naive `new URLSearchParams(location.search)` forward would
  // drag cursor/limit and any future UI-only param along with it.
  it("never forwards cursor, limit, or an unrecognized param for any report identity", () => {
    const params = new URLSearchParams({
      ward_id: "ward-1",
      cursor: "some-opaque-cursor",
      limit: "25",
      some_future_ui_only_param: "x",
    });
    expect(buildPrintDataFilters("receive-report", params)).toEqual({ ward_id: "ward-1" });
  });

  it("returns an empty object when no whitelisted key is present", () => {
    const params = new URLSearchParams({ cursor: "x", limit: "10" });
    expect(buildPrintDataFilters("equipment-verify-checklist", params)).toEqual({});
  });
});
