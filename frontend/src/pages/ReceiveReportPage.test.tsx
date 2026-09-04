import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReceiveReportPage } from "@/pages/ReceiveReportPage";
import type { Category, Page, ReportTransactionOut, Ward } from "@/types";

// Roadmap PR17 Slice 3 (docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md §6.1/
// §7.1/§12): Receive Report screen tests. Consumes GET /reports/receive
// (services/reports.ts's getReceiveReport) only -- GET /transactions is
// never called for this page.

const getReceiveReport = vi.fn();
const getOperatorOptions = vi.fn();
vi.mock("@/services/reports", () => ({
  getReceiveReport: (...args: unknown[]) => getReceiveReport(...args),
  getOperatorOptions: (...args: unknown[]) => getOperatorOptions(...args),
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
    equipment: { id: "eq-1", asset_number: "AST-1", equipment_name: "Infusion Pump", status: "available_at_pool" },
    quantity: 1,
    borrowed_at: "2026-07-10T03:00:00Z",
    returned_at: "2026-07-12T03:00:00Z",
    borrower_name: null,
    ward_id: "ward-1",
    dispatch_type: "on_demand",
    routine_round: null,
    phone_number: null,
    receipt_outcome: "usable",
    legacy_condition_on_return: null,
    status: "closed",
    notes: null,
    dispatch_operator_display_name: "สมชาย ใจดี",
    receipt_operator_display_name: "สมหญิง รักงาน",
    dispatch_business_date: "2026-07-10",
    dispatch_shift: "day",
    receipt_business_date: "2026-07-12",
    receipt_shift: "night",
    ...overrides,
  };
}

beforeEach(() => {
  getReceiveReport.mockResolvedValue(page([makeRow()]));
  getOperatorOptions.mockResolvedValue({ items: [], next_cursor: null, total: 0 });
});

afterEach(() => {
  vi.clearAllMocks();
});

function LocationSearchProbe() {
  const location = useLocation();
  return <div data-testid="location-search">{location.search}</div>;
}

function renderPage(initialPath = "/reports/receive") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <LocationSearchProbe />
        <Routes>
          <Route path="/reports/receive" element={<ReceiveReportPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("ReceiveReportPage", () => {
  it("calls only GET /reports/receive, never GET /transactions", async () => {
    renderPage();
    await waitFor(() => expect(getReceiveReport).toHaveBeenCalled());
  });

  it("renders ReportTransactionOut fields directly, including both operator display names and business_date/shift, without recomputing them", async () => {
    renderPage();

    expect(await screen.findByText("TX-1")).toBeInTheDocument();
    expect(screen.getByText("สมชาย ใจดี")).toBeInTheDocument();
    expect(screen.getByText("สมหญิง รักงาน")).toBeInTheDocument();
    expect(screen.getByText(/2026-07-10/)).toBeInTheDocument();
    expect(screen.getByText(/2026-07-12/)).toBeInTheDocument();
  });

  it("shows a loading state while the report is being fetched", async () => {
    getReceiveReport.mockReturnValue(new Promise(() => {}));
    renderPage();

    expect(await screen.findByText("กำลังโหลดรายงานการรับคืน...")).toBeInTheDocument();
  });

  it("shows an empty state when no rows match", async () => {
    getReceiveReport.mockResolvedValue(page([]));
    renderPage();

    expect(await screen.findByText("ไม่พบรายการ")).toBeInTheDocument();
  });

  it("shows an error state with a retry action, and retry recovers on success", async () => {
    getReceiveReport.mockRejectedValueOnce({
      isAxiosError: true,
      response: { data: { detail: "โหลดไม่สำเร็จ" } },
    });
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("โหลดไม่สำเร็จ")).toBeInTheDocument();
    const retryButton = screen.getByRole("button", { name: "ลองใหม่" });

    getReceiveReport.mockResolvedValueOnce(page([makeRow()]));
    await user.click(retryButton);

    await waitFor(() => expect(screen.queryByText("โหลดไม่สำเร็จ")).not.toBeInTheDocument());
    expect(await screen.findByText("TX-1")).toBeInTheDocument();
  });

  it("never drops or filters a row the backend returned -- the frontend does not re-apply OPEN exclusion or any other eligibility rule", async () => {
    // The backend guarantees every Receive Report row is CLOSED with a
    // completed receipt; this page must render every row it is given,
    // regardless of status/returned_at, never second-guessing the backend.
    getReceiveReport.mockResolvedValue(page([makeRow({ id: "tx-a", transaction_no: "TX-A" }), makeRow({ id: "tx-b", transaction_no: "TX-B" })]));
    renderPage();

    expect(await screen.findByText("TX-A")).toBeInTheDocument();
    expect(screen.getByText("TX-B")).toBeInTheDocument();
  });

  it("appends cursor pages in backend order without re-sorting, merging, or reversing", async () => {
    getReceiveReport.mockResolvedValueOnce(
      page([makeRow({ id: "tx-1", transaction_no: "TX-1" })], "cursor-2")
    );
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("TX-1");
    const loadMore = screen.getByRole("button", { name: "โหลดเพิ่มเติม" });

    getReceiveReport.mockResolvedValueOnce(page([makeRow({ id: "tx-2", transaction_no: "TX-2" })], null));
    await user.click(loadMore);

    await waitFor(() => expect(screen.getByText("TX-2")).toBeInTheDocument());
    const rows = screen.getAllByRole("row").slice(1); // drop header row
    const order = rows.map((r) => r.textContent ?? "");
    expect(order[0]).toContain("TX-1");
    expect(order[1]).toContain("TX-2");
    expect(getReceiveReport).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: "cursor-2" }));
    expect(screen.queryByRole("button", { name: "โหลดเพิ่มเติม" })).not.toBeInTheDocument();
  });

  it('offers "โหลดเพิ่มเติม" only when the backend reports a next_cursor', async () => {
    getReceiveReport.mockResolvedValue(page([makeRow()], null));
    renderPage();
    await screen.findByText("TX-1");

    expect(screen.queryByRole("button", { name: "โหลดเพิ่มเติม" })).not.toBeInTheDocument();
  });

  it("serializes applied filters into the URL and into the getReceiveReport call after นำตัวกรองไปใช้", async () => {
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
      expect(getReceiveReport).toHaveBeenLastCalledWith(
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
    await waitFor(() =>
      expect(getReceiveReport).toHaveBeenLastCalledWith(expect.objectContaining({ shift: "night" }))
    );

    await user.click(screen.getByRole("button", { name: "ล้างตัวกรอง" }));

    await waitFor(() =>
      expect(getReceiveReport).toHaveBeenLastCalledWith(expect.objectContaining({ shift: undefined }))
    );
  });

  it("restores applied filters from the URL on initial render", async () => {
    renderPage("/reports/receive?business_date_from=2026-07-01&shift=night&ward_id=ward-1");
    await screen.findByText("TX-1");

    expect(getReceiveReport).toHaveBeenCalledWith(
      expect.objectContaining({ business_date_from: "2026-07-01", shift: "night", ward_id: "ward-1" })
    );
  });

  // PR67-H1 regression: a URL-restored operator_id must survive an Apply of
  // an unrelated filter change -- the autocomplete's resolved display
  // object legitimately starts null (it cannot be resolved back into a
  // display_name without a second lookup), but that must not be confused
  // with the user having cleared the operator filter.
  it("preserves an existing operator_id from the URL when Apply is pressed after changing an unrelated filter", async () => {
    const user = userEvent.setup();
    renderPage("/reports/receive?operator_id=op-1");
    await screen.findByText("TX-1");

    await user.selectOptions(screen.getByLabelText("กะ"), "day");
    await user.click(screen.getByRole("button", { name: "นำตัวกรองไปใช้" }));

    await waitFor(() =>
      expect(getReceiveReport).toHaveBeenLastCalledWith(
        expect.objectContaining({ operator_id: "op-1", shift: "day" })
      )
    );
    const search = screen.getByTestId("location-search").textContent ?? "";
    expect(search).toContain("operator_id=op-1");
  });

  it("removes operator_id only when the operator selection is explicitly cleared", async () => {
    const staff = { id: "op-1", display_name: "สมชาย ใจดี", is_active: true };
    getOperatorOptions.mockResolvedValue({ items: [staff], next_cursor: null, total: 1 });
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("TX-1");

    await user.click(screen.getByLabelText("ผู้ปฏิบัติงาน"));
    await user.click(await screen.findByRole("button", { name: "สมชาย ใจดี" }));
    await user.click(screen.getByRole("button", { name: "นำตัวกรองไปใช้" }));

    await waitFor(() =>
      expect(getReceiveReport).toHaveBeenLastCalledWith(expect.objectContaining({ operator_id: "op-1" }))
    );
    expect(screen.getByTestId("location-search").textContent ?? "").toContain("operator_id=op-1");

    await user.click(screen.getByRole("button", { name: "ล้างผู้ปฏิบัติงานที่เลือก" }));
    await user.click(screen.getByRole("button", { name: "นำตัวกรองไปใช้" }));

    await waitFor(() =>
      expect(getReceiveReport).toHaveBeenLastCalledWith(expect.objectContaining({ operator_id: undefined }))
    );
    expect(screen.getByTestId("location-search").textContent ?? "").not.toContain("operator_id");
  });

  // Roadmap PR18C: the print link must carry this page's exact current URL
  // filters over to the dedicated print view, using report identity
  // "receive-report".
  it('offers a "พิมพ์รายงาน" link to the print view carrying the current applied filters', async () => {
    renderPage("/reports/receive?ward_id=ward-1&shift=day");
    await screen.findByText("TX-1");

    const printLink = screen.getByRole("link", { name: "พิมพ์รายงาน" });
    expect(printLink).toHaveAttribute("href", "/reports/receive-report/print?ward_id=ward-1&shift=day");
    expect(printLink).toHaveAttribute("target", "_blank");
  });
});
