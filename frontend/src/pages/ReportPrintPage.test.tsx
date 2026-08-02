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

// Only getReportPrintData is mocked -- buildPrintDataFilters is the real
// implementation, so these tests exercise the actual request-construction
// behavior end to end. Pagination stripping (cursor/limit) is enforced
// inside getReportPrintData itself (review round 2, PR18C-H2R) and is
// covered separately in printReports.test.ts, since it is mocked away here.
const getReportPrintData = vi.fn();
vi.mock("@/services/printReports", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/printReports")>();
  return {
    ...actual,
    getReportPrintData: (...args: unknown[]) => getReportPrintData(...args),
  };
});

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
// controllable promise (resolvable *or* rejectable) returned from
// `document.fonts.load()`, so both the "print only after fonts ready"
// gating and the fail-closed rejection path (design §9; review round 3,
// PR18C-H1R2) can be deterministically observed. `document.fonts.load()`,
// not `document.fonts.ready`, is stubbed here: per the CSS Font Loading
// Module Level 3 spec, `document.fonts.ready` never rejects, so it cannot
// signal a font-load failure -- see hooks/usePrintFontsReady.ts for the
// full explanation of why this hook uses `load()` instead.
let resolveFontsReady: () => void;
let rejectFontsReady: () => void;

function installControllableFonts() {
  const fontsLoadPromise = new Promise<void>((resolve, reject) => {
    resolveFontsReady = resolve;
    rejectFontsReady = reject;
  });
  Object.defineProperty(document, "fonts", {
    configurable: true,
    value: { load: () => fontsLoadPromise },
  });
}

beforeEach(() => {
  installControllableFonts();
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

  // Roadmap PR18C review round 2 (PR18C-H2R): the page must never decide
  // which filters are applicable to which report identity -- that decision
  // belongs to the backend's own `_reject_inapplicable_print_data_filters`
  // alone. Every filter present on the URL -- including one inapplicable to
  // this report identity, and an entirely unrecognized one -- reaches the
  // request unchanged, so the backend can validate it and return a
  // structured 400 INVALID_INPUT rather than the frontend silently
  // discarding it. `cursor`/`limit` still appear in the object the page
  // passes to `getReportPrintData` here -- their removal happens inside the
  // service itself (see printReports.test.ts), not this page.
  it("forwards every URL filter to the print-data request unmodified, dropping none", async () => {
    renderPage(
      "/reports/equipment-verify-checklist/print?status=available_at_pool&shift=day&cursor=abc&limit=25&some_unknown_param=x"
    );
    await waitFor(() =>
      expect(getReportPrintData).toHaveBeenCalledWith("equipment-verify-checklist", {
        status: "available_at_pool",
        shift: "day",
        cursor: "abc",
        limit: "25",
        some_unknown_param: "x",
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

  // Roadmap PR18C review round 2 (PR18C-H1R), still true after round 3's
  // switch to document.fonts.load(): readiness is report-loaded AND
  // fonts-ready -- resolving the font check early (even before the report
  // data has arrived) must not enable the Print button by itself. Proves
  // the font-load check is not started until a document exists.
  it("stays disabled if fonts resolve before the report has loaded, and enables only once the report has also loaded", async () => {
    let resolveReport: (doc: ReturnType<typeof makeDocument>) => void;
    getReportPrintData.mockReturnValue(
      new Promise((resolve) => {
        resolveReport = resolve;
      })
    );
    renderPage();

    // Fonts resolve immediately -- before the report document exists at all.
    resolveFontsReady();
    const printButton = await screen.findByRole("button", { name: "พิมพ์" });
    expect(printButton).toBeDisabled();

    resolveReport!(makeDocument());
    await waitFor(() => expect(printButton).not.toBeDisabled());
  });

  // Roadmap PR18C review round 3 (PR18C-H1R2): readiness must be fail-closed
  // -- a rejected document.fonts.load() check (a real, spec-defined
  // rejection, not document.fonts.ready which never rejects) must never
  // enable Print.
  it("is fail-closed: a rejected font readiness check keeps Print disabled and shows a Thai error", async () => {
    renderPage();
    await screen.findByText("รายงานการรับคืน");
    const printButton = screen.getByRole("button", { name: "พิมพ์" });
    expect(printButton).toBeDisabled();

    rejectFontsReady();

    expect(await screen.findByText("ไม่สามารถเตรียมฟอนต์สำหรับพิมพ์ได้ กรุณาลองใหม่ก่อนพิมพ์")).toBeInTheDocument();
    expect(printButton).toBeDisabled();
  });

  it("exposes a retry action for a failed font readiness check, and recovers once retried successfully", async () => {
    renderPage();
    await screen.findByText("รายงานการรับคืน");
    rejectFontsReady();

    const fontsRetryButton = await screen.findByRole("button", { name: "ลองใหม่" });

    // A fresh, resolvable document.fonts.load() promise is what a real
    // browser retry would observe (e.g. after a transient network failure
    // resolves on a subsequent attempt).
    installControllableFonts();
    const { default: userEvent } = await import("@testing-library/user-event");
    await userEvent.setup().click(fontsRetryButton);

    resolveFontsReady();
    await waitFor(() => expect(screen.getByRole("button", { name: "พิมพ์" })).not.toBeDisabled());
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

  // Roadmap PR18C review round 3 (PR18C-H1R2): window.print() must never be
  // reachable while font readiness has failed -- the disabled attribute is
  // the primary guard (a disabled <button> never dispatches a click event),
  // and handlePrint's own `!isReady` check is the defense-in-depth backstop.
  it("never calls window.print() while font readiness has failed", async () => {
    const printSpy = vi.spyOn(window, "print").mockImplementation(() => {});
    renderPage();
    await screen.findByText("รายงานการรับคืน");
    rejectFontsReady();
    await screen.findByText("ไม่สามารถเตรียมฟอนต์สำหรับพิมพ์ได้ กรุณาลองใหม่ก่อนพิมพ์");

    const printButton = screen.getByRole("button", { name: "พิมพ์" });
    const { default: userEvent } = await import("@testing-library/user-event");
    await userEvent.setup().click(printButton);

    expect(printSpy).not.toHaveBeenCalled();
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
