import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/services/api";
import { getReportPrintData } from "@/services/printReports";

// Roadmap PR18C (docs/design/PR18_PRINTING_EXPORT_PLAN.md §6.2/§9): proves
// the print client calls exactly the merged PR18B endpoint
// (GET /reports/{report_id}/print-data) with the filters forwarded
// verbatim -- no `limit`/`cursor`, no client-side filter narrowing.

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
