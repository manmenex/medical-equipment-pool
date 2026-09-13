import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/services/api";
import { buildPrintDataFilters, getReportPrintData, stripPrintDataPaginationParams } from "@/services/printReports";

// Roadmap PR18C (docs/design/PR18_PRINTING_EXPORT_PLAN.md §6.2/§9): proves
// the print client calls exactly the merged PR18B endpoint
// (GET /reports/{report_id}/print-data) with the filters it was given, with
// only `cursor`/`limit` ever removed. Review round 2 (PR18C-H2R) requires
// this removal to be enforced inside `getReportPrintData` itself -- not
// only by page-level preprocessing -- so a caller cannot leak pagination
// parameters through this service even if it bypasses ReportPrintPage.

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

  // Roadmap PR18C review round 2 (PR18C-H2R): a caller passing `cursor`
  // and/or `limit` directly to this service -- bypassing any page-level
  // preprocessing entirely -- must still never have them reach the network
  // request. This is the defense-in-depth guarantee the review requires.
  it("strips cursor and limit even when a caller passes them directly to this service, bypassing the page", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { metadata: {}, columns: [], rows: [] } });

    await getReportPrintData("receive-report", { ward_id: "ward-1", cursor: "some-opaque-cursor", limit: "25" });

    expect(getSpy).toHaveBeenCalledWith("/reports/receive-report/print-data", {
      params: { ward_id: "ward-1" },
    });
  });

  // Roadmap PR18C review round 2 (PR18C-H2R): every other parameter --
  // including one this report identity does not accept, and one the
  // backend does not recognize at all -- is preserved untouched, so the
  // backend's own `_reject_inapplicable_print_data_filters` remains the
  // single, authoritative place that validates it (returning a structured
  // 400 INVALID_INPUT) rather than the frontend silently discarding it.
  it("preserves a report-inapplicable filter and an unrecognized filter, letting the backend validate them", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { metadata: {}, columns: [], rows: [] } });

    await getReportPrintData("equipment-verify-checklist", {
      status: "available_at_pool",
      shift: "day",
      some_unknown_param: "x",
    });

    expect(getSpy).toHaveBeenCalledWith("/reports/equipment-verify-checklist/print-data", {
      params: { status: "available_at_pool", shift: "day", some_unknown_param: "x" },
    });
  });

  it("propagates a structured backend error (e.g. 400 INVALID_INPUT) to the caller unchanged", async () => {
    const backendError = {
      isAxiosError: true,
      response: { status: 400, data: { detail: "The following filters are not supported for report_id 'equipment-verify-checklist': shift" } },
    };
    vi.spyOn(api, "get").mockRejectedValue(backendError);

    await expect(getReportPrintData("equipment-verify-checklist", { shift: "day" })).rejects.toBe(backendError);
  });

  it("never targets GET /transactions or another endpoint", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { metadata: {}, columns: [], rows: [] } });
    await getReportPrintData("receive-report", {});
    expect(getSpy).not.toHaveBeenCalledWith("/transactions", expect.anything());
  });
});

describe("stripPrintDataPaginationParams", () => {
  it("removes cursor", () => {
    expect(stripPrintDataPaginationParams({ ward_id: "ward-1", cursor: "abc" })).toEqual({ ward_id: "ward-1" });
  });

  it("removes limit", () => {
    expect(stripPrintDataPaginationParams({ ward_id: "ward-1", limit: "25" })).toEqual({ ward_id: "ward-1" });
  });

  it("removes both cursor and limit together", () => {
    expect(stripPrintDataPaginationParams({ ward_id: "ward-1", cursor: "abc", limit: "25" })).toEqual({
      ward_id: "ward-1",
    });
  });

  it("preserves every other key and value unchanged, including ones the current report identity may not accept", () => {
    const input = {
      business_date_from: "2026-07-01",
      shift: "day",
      dispatch_type: "on_demand",
      some_unknown_param: "x",
    };
    expect(stripPrintDataPaginationParams(input)).toEqual(input);
  });

  it("does not mutate its input", () => {
    const input = { cursor: "abc", ward_id: "ward-1" };
    stripPrintDataPaginationParams(input);
    expect(input).toEqual({ cursor: "abc", ward_id: "ward-1" });
  });

  it("returns an empty object for an empty input", () => {
    expect(stripPrintDataPaginationParams({})).toEqual({});
  });
});

describe("buildPrintDataFilters", () => {
  // Roadmap PR18C review round 2 (PR18C-H2R): this function is a plain,
  // total passthrough of every query param present on the URL -- it must
  // never re-implement an allowlist of "applicable" filters (the first
  // review round's now-removed PRINT_DATA_FILTER_KEYS did exactly that, and
  // was found to silently discard filters the backend should instead
  // validate and reject with a structured error).
  it("returns every query param present, unfiltered", () => {
    const params = new URLSearchParams({
      business_date_from: "2026-07-01",
      shift: "day",
      ward_id: "ward-1",
      dispatch_type: "on_demand",
      routine_round: "06:00",
      status: "available_at_pool",
      some_unknown_param: "x",
    });
    expect(buildPrintDataFilters(params)).toEqual({
      business_date_from: "2026-07-01",
      shift: "day",
      ward_id: "ward-1",
      dispatch_type: "on_demand",
      routine_round: "06:00",
      status: "available_at_pool",
      some_unknown_param: "x",
    });
  });

  it("still includes cursor/limit if present -- their removal is the service's responsibility, not this function's", () => {
    const params = new URLSearchParams({ ward_id: "ward-1", cursor: "abc", limit: "25" });
    expect(buildPrintDataFilters(params)).toEqual({ ward_id: "ward-1", cursor: "abc", limit: "25" });
  });

  it("returns an empty object for an empty URL", () => {
    expect(buildPrintDataFilters(new URLSearchParams())).toEqual({});
  });
});
