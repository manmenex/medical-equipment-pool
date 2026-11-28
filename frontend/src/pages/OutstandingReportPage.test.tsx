import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OutstandingReportPage } from "@/pages/OutstandingReportPage";

const fetchOutstanding = vi.fn();
const fetchOutstandingLineText = vi.fn();
vi.mock("@/services/outstandingReport", () => ({
  fetchOutstanding: (...a: unknown[]) => fetchOutstanding(...a),
  fetchOutstandingLineText: (...a: unknown[]) => fetchOutstandingLineText(...a),
}));

const row = (n: string, hn: boolean) => ({
  transaction_no: n,
  bcm_code: `BCM-${n}`,
  equipment_name: `Pump ${n}`,
  category: "Infusion",
  source: "pool",
  source_badge: null,
  ward: "Ward A",
  borrowed_at: "2026-11-01T03:00:00+07:00",
  age_days: 27,
  keyer: "สมชาย",
  has_hn: hn,
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <OutstandingReportPage />
    </QueryClientProvider>
  );
}

describe("OutstandingReportPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchOutstanding.mockResolvedValue({
      days: 7,
      total: 2,
      wards: [{ ward: "Ward A", count: 2, rows: [row("1", true), row("2", false)] }],
    });
    fetchOutstandingLineText.mockResolvedValue("LINE TEXT");
  });

  it("renders ward groups, counts, and the screen-only HN column", async () => {
    renderPage();
    expect(await screen.findByText("Ward A (2)")).toBeInTheDocument();
    expect(screen.getByText("รวม 2 เครื่อง")).toBeInTheDocument();
    expect(fetchOutstanding).toHaveBeenCalledWith(7);
    const screenSection = screen.getByRole("region", { name: "Ward A" });
    expect(within(screenSection).getByRole("columnheader", { name: "มี HN" })).toBeInTheDocument();
    expect(within(screenSection).getAllByText("มี HN").length).toBe(2);
  });

  it("refetches when the days input changes", async () => {
    renderPage();
    await screen.findByText("Ward A (2)");
    const input = screen.getByLabelText("ค้างเกิน (วัน)");
    await userEvent.clear(input);
    await userEvent.type(input, "14");
    await waitFor(() => expect(fetchOutstanding).toHaveBeenLastCalledWith(14));
  });

  it("copies the LINE text", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderPage();
    await screen.findByText("Ward A (2)");
    await userEvent.click(screen.getByRole("button", { name: "คัดลอกข้อความ LINE" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("LINE TEXT"));
    expect(await screen.findByText("คัดลอกแล้ว")).toBeInTheDocument();
  });

  it("print view is landscape and has no HN column", async () => {
    const { container } = renderPage();
    await screen.findByText("Ward A (2)");
    const print = screen.getByTestId("print-view");
    expect(container.querySelector('[data-orientation="landscape"]')).not.toBeNull();
    expect(within(print).queryByText(/HN/)).toBeNull();
    expect(within(print).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "หน่วยงาน", "BCM", "เครื่อง", "วันที่เบิก", "ค้าง (วัน)", "BME",
    ]);
  });
});
