import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReportPrintPage } from "@/pages/ReportPrintPage";
import type { PrintDocumentOut } from "@/types";

// Roadmap PR18C (docs/design/PR18_PRINTING_EXPORT_PLAN.md §9/§20.3): the
// dedicated browser-print view. Consumes GET /reports/{report_id}/print-data
// (services/printReports.ts's getReportPrintData) only -- it must never
// call GET /reports/receive, GET /reports/issue,
// GET /reports/equipment-verify-checklist, or GET /transactions to
// reconstruct a report, and it must render exactly the backend-given
// column/row order without filtering, sorting, or recomputing anything.

const getReportPrintData = vi.fn();
vi.mock("@/services/printReports", () => ({
  getReportPrintData: (...args: unknown[]) => getReportPrintData(...args),
}));

function makeDocument(overrides: Partial<PrintDocumentOut> = {}): PrintDocumentOut {
  return {
    metadata: {
      report_identity: "receive-report",
      display_name_th: "รายงานการรับคืน",
      template_version: "1",
      generated_at: "2026-07-31T03:15:00+00:00",
      generated_by_display_name: "สมชาย ใจดี",
      generated_by_user_id: "user-1",
      timezone: "Asia/Bangkok",
      applied_filters: [{ label_th: "หอผู้ป่วย", value: "Ward A" }],
      row_count: 1,
      filename_stem: "receive-report_all_all_20260731T031500Z",
    },
    columns: [
      { key: "transaction_no", label_th: "เลขที่รายการ", value_type: "string" },
      { key: "asset_number", label_th: "รหัสครุภัณฑ์", value_type: "string" },
    ],
    rows: [{ values: { transaction_no: "TX-1", asset_number: "AST-1" } }],
    ...overrides,
  };
}

// jsdom does not implement the Font Loading API -- stubbed here as a
// controllable, resolvable promise so the "print only after fonts ready"
// gating (design §9) can be deterministically observed instead of relying
// on the component's own environment-detection fallback.
let resolveFontsReady: () => void;
beforeEach(() => {
  const fontsReadyPromise = new Promise<void>((resolve) => {
    resolveFontsReady = resolve;
  });
  Object.defineProperty(document, "fonts", {
    configurable: true,
    value: { ready: fontsReadyPromise },
  });
  getReportPrintData.mockResolvedValue(makeDocument());
});

afterEach(() => {
  vi.clearAllMocks();
  delete (document as unknown as { fonts?: unknown }).fonts;
});

function renderPage(initialPath = "/reports/receive-report/print") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/reports/:reportId/print" element={<ReportPrintPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("ReportPrintPage", () => {
  it("calls only GET /reports/{report_id}/print-data for the report identity in the route", async () => {
    renderPage("/reports/receive-report/print?ward_id=ward-1");
    await waitFor(() =>
      expect(getReportPrintData).toHaveBeenCalledWith("receive-report", { ward_id: "ward-1" })
    );
  });

  it("forwards every URL query param as a filter, unmodified", async () => {
    renderPage("/reports/issue-report/print?ward_id=ward-1&shift=day&dispatch_type=on_demand");
    await waitFor(() =>
      expect(getReportPrintData).toHaveBeenCalledWith("issue-report", {
        ward_id: "ward-1",
        shift: "day",
        dispatch_type: "on_demand",
      })
    );
  });

  it("shows an explicit error and never calls the API for an unrecognized report identity", async () => {
    renderPage("/reports/not-a-real-report/print");
    expect(await screen.findByText("ไม่รู้จักรายงานนี้ ไม่สามารถแสดงหน้าพิมพ์ได้")).toBeInTheDocument();
    expect(getReportPrintData).not.toHaveBeenCalled();
  });

  it("shows a loading state while the document is being fetched", async () => {
    getReportPrintData.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(await screen.findByText("กำลังโหลดเอกสาร...")).toBeInTheDocument();
  });

  it("shows an error state with a retry action, and retry recovers on success", async () => {
    getReportPrintData.mockRejectedValueOnce({
      isAxiosError: true,
      response: { data: { detail: "ตัวกรองนี้ไม่รองรับสำหรับรายงานนี้" } },
    });
    renderPage();

    expect(await screen.findByText("ตัวกรองนี้ไม่รองรับสำหรับรายงานนี้")).toBeInTheDocument();
    const retryButton = screen.getByRole("button", { name: "ลองใหม่" });

    getReportPrintData.mockResolvedValueOnce(makeDocument());
    resolveFontsReady();
    const { default: userEvent } = await import("@testing-library/user-event");
    await userEvent.setup().click(retryButton);

    await waitFor(() => expect(screen.queryByText("ตัวกรองนี้ไม่รองรับสำหรับรายงานนี้")).not.toBeInTheDocument());
    expect(await screen.findByText("รายงานการรับคืน")).toBeInTheDocument();
  });

  it("renders report identity, generated-by, timezone, template version, and the human-readable filter summary from the backend", async () => {
    renderPage();

    expect(await screen.findByText("รายงานการรับคืน")).toBeInTheDocument();
    expect(screen.getByText("สมชาย ใจดี")).toBeInTheDocument();
    expect(screen.getAllByText(/Asia\/Bangkok/).length).toBeGreaterThan(0);
    expect(screen.getByText(/หอผู้ป่วย/)).toBeInTheDocument();
    expect(screen.getByText("Ward A")).toBeInTheDocument();
    expect(screen.getByText(/พบทั้งหมด 1 รายการ/)).toBeInTheDocument();
  });

  it("renders columns and row values in exactly the backend-given order -- never re-sorted or re-filtered", async () => {
    renderPage();
    await screen.findByText("รายงานการรับคืน");

    const table = within(screen.getByRole("table"));
    const headerCells = table.getAllByRole("columnheader").map((c) => c.textContent);
    expect(headerCells).toEqual(["เลขที่รายการ", "รหัสครุภัณฑ์"]);

    const dataRows = table.getAllByRole("row").slice(1);
    expect(dataRows).toHaveLength(1);
    expect(dataRows[0].textContent).toBe("TX-1AST-1");
  });

  it("renders a clear Thai empty-state message for a zero-row document, without treating it as an error", async () => {
    getReportPrintData.mockResolvedValue(
      makeDocument({ rows: [], metadata: { ...makeDocument().metadata, row_count: 0 } })
    );
    renderPage();

    expect(await screen.findByText("ไม่พบข้อมูลตามตัวกรองที่เลือก")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("keeps the Print button disabled until data has loaded and fonts are ready, then enables it", async () => {
    renderPage();
    await screen.findByText("รายงานการรับคืน");

    const printButton = screen.getByRole("button", { name: "พิมพ์" });
    expect(printButton).toBeDisabled();

    resolveFontsReady();
    await waitFor(() => expect(printButton).not.toBeDisabled());
  });

  it("never calls window.print() automatically before the Print button is clicked", async () => {
    const printSpy = vi.spyOn(window, "print").mockImplementation(() => {});
    renderPage();
    await screen.findByText("รายงานการรับคืน");
    resolveFontsReady();
    await waitFor(() => expect(screen.getByRole("button", { name: "พิมพ์" })).not.toBeDisabled());

    expect(printSpy).not.toHaveBeenCalled();
  });

  it("calls window.print() when the Print button is clicked after readiness", async () => {
    const printSpy = vi.spyOn(window, "print").mockImplementation(() => {});
    renderPage();
    await screen.findByText("รายงานการรับคืน");
    resolveFontsReady();

    const printButton = await waitFor(() => {
      const btn = screen.getByRole("button", { name: "พิมพ์" });
      expect(btn).not.toBeDisabled();
      return btn;
    });

    const { default: userEvent } = await import("@testing-library/user-event");
    await userEvent.setup().click(printButton);

    expect(printSpy).toHaveBeenCalledTimes(1);
  });

  it("marks the on-screen preview toolbar as print-hidden (no-print) so it never appears in the printed output", async () => {
    renderPage();
    await screen.findByText("รายงานการรับคืน");

    const printButton = screen.getByRole("button", { name: "พิมพ์" });
    // The toolbar containing the Print/Close controls must carry the
    // .no-print class defined in styles/print.css.
    expect(printButton.closest(".no-print")).not.toBeNull();
  });
});
