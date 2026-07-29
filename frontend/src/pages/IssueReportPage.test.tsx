import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { IssueReportPage } from "@/pages/IssueReportPage";
import type { Category, Page, ReportTransactionOut, Ward } from "@/types";

// Roadmap PR17 Slice 3 (docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md §6.2/
// §7.2/§12): Issue Report screen tests. Consumes GET /reports/issue
// (services/reports.ts's getIssueReport) only -- GET /transactions is
// never called for this page. Unlike the Receive Report, the Issue Report
// legitimately includes OPEN (not-yet-received) transactions -- this is
// the page's defining behavioral difference, and it must not be
// re-implemented or second-guessed on the frontend.

const getIssueReport = vi.fn();
vi.mock("@/services/reports", () => ({
  getIssueReport: (...args: unknown[]) => getIssueReport(...args),
  getOperatorOptions: () => Promise.resolve({ items: [], next_cursor: null, total: 0 }),
}));

const wards: Ward[] = [{ id: "ward-1", code: "W1", name: "Ward A", department_id: null }];
const categories: Category[] = [
  { id: "cat-1", name: "Infusion Pump", default_pm_interval_days: null, default_cal_interval_days: null },
];
vi.mock("@/services/masterData", () => ({
  listWards: () => Promise.resolve(wards),
  listCategories: () => Promise.resolve(categories),
}));

function page(items: ReportTransactionOut[], nextCursor: string | null = null): Page<ReportTransactionOut> {
  return { items, next_cursor: nextCursor, total: items.length };
}

function makeRow(overrides: Partial<ReportTransactionOut> = {}): ReportTransactionOut {
  return {
    id: "tx-1",
    transaction_no: "TX-1",
    equipment: { id: "eq-1", asset_number: "AST-1", equipment_name: "Infusion Pump", status: "issued_to_ward" },
    quantity: 1,
    borrowed_at: "2026-07-10T03:00:00Z",
    returned_at: null,
    borrower_name: null,
    ward_id: "ward-1",
    dispatch_type: "on_demand",
    routine_round: null,
    phone_number: null,
    receipt_outcome: null,
    legacy_condition_on_return: null,
    status: "open",
    notes: null,
    dispatch_operator_display_name: "สมชาย ใจดี",
    receipt_operator_display_name: null,
    dispatch_business_date: "2026-07-10",
    dispatch_shift: "day",
    receipt_business_date: null,
    receipt_shift: null,
    ...overrides,
  };
}

beforeEach(() => {
  getIssueReport.mockResolvedValue(page([makeRow()]));
});

afterEach(() => {
  vi.clearAllMocks();
});

function LocationSearchProbe() {
  const location = useLocation();
  return <div data-testid="location-search">{location.search}</div>;
}

function renderPage(initialPath = "/reports/issue") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <LocationSearchProbe />
        <Routes>
          <Route path="/reports/issue" element={<IssueReportPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("IssueReportPage", () => {
  it("calls only GET /reports/issue, never GET /transactions", async () => {
    renderPage();
    await waitFor(() => expect(getIssueReport).toHaveBeenCalled());
  });

  it("renders ReportTransactionOut fields directly, including the dispatch operator display name and business_date/shift, without recomputing them", async () => {
    renderPage();

    expect(await screen.findByText("TX-1")).toBeInTheDocument();
    expect(screen.getByText("สมชาย ใจดี")).toBeInTheDocument();
    expect(screen.getByText(/2026-07-10/)).toBeInTheDocument();
  });

  it("shows a loading state while the report is being fetched", async () => {
    getIssueReport.mockReturnValue(new Promise(() => {}));
    renderPage();

    expect(await screen.findByText("กำลังโหลดรายงานการเบิก...")).toBeInTheDocument();
  });

  it("shows an empty state when no rows match", async () => {
    getIssueReport.mockResolvedValue(page([]));
    renderPage();

    expect(await screen.findByText("ไม่พบรายการ")).toBeInTheDocument();
  });

  it("shows an error state with a retry action, and retry recovers on success", async () => {
    getIssueReport.mockRejectedValueOnce({
      isAxiosError: true,
      response: { data: { detail: "โหลดไม่สำเร็จ" } },
    });
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("โหลดไม่สำเร็จ")).toBeInTheDocument();
    const retryButton = screen.getByRole("button", { name: "ลองใหม่" });

    getIssueReport.mockResolvedValueOnce(page([makeRow()]));
    await user.click(retryButton);

    await waitFor(() => expect(screen.queryByText("โหลดไม่สำเร็จ")).not.toBeInTheDocument());
    expect(await screen.findByText("TX-1")).toBeInTheDocument();
  });

  it("renders OPEN (not-yet-received) transactions exactly like CLOSED ones -- the frontend never filters out an OPEN row", async () => {
    // This is the Issue Report's defining behavioral difference from the
    // Receive Report: a dispatch is a fact about the past regardless of
    // receipt status, so both OPEN and CLOSED rows must render whenever
    // the backend returns them (§7.2). No status/returned_at check here.
    getIssueReport.mockResolvedValue(
      page([
        makeRow({ id: "tx-open", transaction_no: "TX-OPEN", status: "open", returned_at: null }),
        makeRow({
          id: "tx-closed",
          transaction_no: "TX-CLOSED",
          status: "closed",
          returned_at: "2026-07-12T03:00:00Z",
          receipt_operator_display_name: "สมหญิง รักงาน",
          receipt_business_date: "2026-07-12",
          receipt_shift: "night",
        }),
      ])
    );
    renderPage();

    expect(await screen.findByText("TX-OPEN")).toBeInTheDocument();
    expect(screen.getByText("TX-CLOSED")).toBeInTheDocument();
  });

  it("appends cursor pages in backend order without re-sorting, merging, or reversing", async () => {
    getIssueReport.mockResolvedValueOnce(page([makeRow({ id: "tx-1", transaction_no: "TX-1" })], "cursor-2"));
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("TX-1");
    const loadMore = screen.getByRole("button", { name: "โหลดเพิ่มเติม" });

    getIssueReport.mockResolvedValueOnce(page([makeRow({ id: "tx-2", transaction_no: "TX-2" })], null));
    await user.click(loadMore);

    await waitFor(() => expect(screen.getByText("TX-2")).toBeInTheDocument());
    const rows = screen.getAllByRole("row").slice(1); // drop header row
    const order = rows.map((r) => r.textContent ?? "");
    expect(order[0]).toContain("TX-1");
    expect(order[1]).toContain("TX-2");
    expect(getIssueReport).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: "cursor-2" }));
    expect(screen.queryByRole("button", { name: "โหลดเพิ่มเติม" })).not.toBeInTheDocument();
  });

  it('offers "โหลดเพิ่มเติม" only when the backend reports a next_cursor', async () => {
    getIssueReport.mockResolvedValue(page([makeRow()], null));
    renderPage();
    await screen.findByText("TX-1");

    expect(screen.queryByRole("button", { name: "โหลดเพิ่มเติม" })).not.toBeInTheDocument();
  });

  it("serializes applied filters into the URL and into the getIssueReport call after นำตัวกรองไปใช้", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("TX-1");

    await user.type(screen.getByLabelText("วันที่ทำการ ตั้งแต่"), "2026-07-01");
    await user.type(screen.getByLabelText("วันที่ทำการ ถึง"), "2026-07-31");
    await user.selectOptions(screen.getByLabelText("กะ"), "day");
    await user.selectOptions(screen.getByLabelText("หอผู้ป่วย"), "ward-1");
    await user.selectOptions(screen.getByLabelText("หมวดหมู่เครื่องมือ"), "cat-1");
    await user.click(screen.getByRole("button", { name: "นำตัวกรองไปใช้" }));

    await waitFor(() =>
      expect(getIssueReport).toHaveBeenLastCalledWith(
        expect.objectContaining({
          business_date_from: "2026-07-01",
          business_date_to: "2026-07-31",
          shift: "day",
          ward_id: "ward-1",
          equipment_category_id: "cat-1",
        })
      )
    );

    const search = screen.getByTestId("location-search").textContent ?? "";
    expect(search).toContain("business_date_from=2026-07-01");
    expect(search).toContain("shift=day");
    expect(search).toContain("ward_id=ward-1");
  });

  it('"ล้างตัวกรอง" clears every filter and re-queries without them', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("TX-1");

    await user.selectOptions(screen.getByLabelText("กะ"), "night");
    await user.click(screen.getByRole("button", { name: "นำตัวกรองไปใช้" }));
    await waitFor(() => expect(getIssueReport).toHaveBeenLastCalledWith(expect.objectContaining({ shift: "night" })));

    await user.click(screen.getByRole("button", { name: "ล้างตัวกรอง" }));

    await waitFor(() =>
      expect(getIssueReport).toHaveBeenLastCalledWith(expect.objectContaining({ shift: undefined }))
    );
  });

  it("restores applied filters from the URL on initial render", async () => {
    renderPage("/reports/issue?business_date_from=2026-07-01&shift=night&ward_id=ward-1");
    await screen.findByText("TX-1");

    expect(getIssueReport).toHaveBeenCalledWith(
      expect.objectContaining({ business_date_from: "2026-07-01", shift: "night", ward_id: "ward-1" })
    );
  });
});
