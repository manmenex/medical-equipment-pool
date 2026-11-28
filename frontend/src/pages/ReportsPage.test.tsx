import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReportsPage } from "@/pages/ReportsPage";

const get = vi.hoisted(() => vi.fn());
vi.mock("@/services/api", () => ({ api: { get } }));
vi.mock("@/services/dashboard", () => ({ fetchBorrowTrend: () => Promise.resolve([]) }));
vi.mock("@/components/DailyReportPanel", () => ({ DailyReportPanel: () => null }));
vi.mock("recharts", () => ({
  BarChart: () => null,
  Bar: () => null,
  CartesianGrid: () => null,
  ResponsiveContainer: () => null,
  Tooltip: () => null,
  XAxis: () => null,
  YAxis: () => null,
}));

afterEach(() => vi.clearAllMocks());

describe("ReportsPage export", () => {
  it("sends the selected range as date_from/date_to and wraps the header buttons", async () => {
    get.mockResolvedValue({ data: new Blob(["x"]) });
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <ReportsPage />
        </MemoryRouter>
      </QueryClientProvider>
    );

    await user.click(screen.getByRole("button", { name: "ส่งออก CSV" }));
    await waitFor(() => expect(get).toHaveBeenCalled());
    const [url, config] = get.mock.calls[0];
    expect(url).toBe("/reports/export");
    expect(config.params.format).toBe("csv");
    expect(config.params.date_from).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(config.params.date_to).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(config.params.date_from < config.params.date_to).toBe(true);
    expect(screen.getByRole("button", { name: "ส่งออก CSV" }).parentElement?.className).toContain("flex-wrap");
  });
});
