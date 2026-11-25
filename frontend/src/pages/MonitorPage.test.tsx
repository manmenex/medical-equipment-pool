import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MonitorPage, groupEvents } from "@/pages/MonitorPage";
import type { MonitorEvent } from "@/services/monitor";

const fetchMonitorEvents = vi.fn();
const listWards = vi.fn();

vi.mock("@/services/monitor", () => ({
  fetchMonitorEvents: (...a: unknown[]) => fetchMonitorEvents(...a),
}));
vi.mock("@/services/masterData", () => ({ listWards: (...a: unknown[]) => listWards(...a) }));

function ev(id: string, over: Partial<MonitorEvent> = {}): MonitorEvent {
  return {
    id,
    kind: "dispatch",
    event_at: "2026-07-28T03:00:10Z",
    business_date: "2026-07-28",
    shift: "day",
    ward: { id: "w1", name: "ICU" },
    operator: { id: "u1", full_name: "Somchai" },
    equipment: { id: `e${id}`, bcm_code: `BCM-${id}`, name: "Pump", category: null },
    receipt_outcome: null,
    close_reason: null,
    ...over,
  };
}

function setup() {
  fetchMonitorEvents.mockImplementation(async ({ kind, ward_id }: { kind: string; ward_id?: string }) => {
    if (kind === "receipt") {
      const items = [ev("R1", { kind: "receipt", receipt_outcome: "defective", shift: "night", business_date: "2026-07-27" })];
      return { items, next_cursor: null, total: 1 };
    }
    const items = ward_id ? [ev("3")] : [ev("1"), ev("2"), ev("3", { ward: { id: "w2", name: "ER" } })];
    return { items, next_cursor: null, total: items.length };
  });
  listWards.mockResolvedValue([
    { id: "w1", code: "W1", name: "ICU", department_id: null },
    { id: "w2", code: "W2", name: "ER", department_id: null },
  ]);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MonitorPage />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.clearAllMocks());

describe("groupEvents", () => {
  it("groups by date+shift and merges same ward/operator/minute into one submission", () => {
    const g = groupEvents([ev("1"), ev("2"), ev("3", { ward: { id: "w2", name: "ER" } }), ev("4", { shift: "night" })]);
    expect(g).toHaveLength(2);
    expect(g[0].submissions).toHaveLength(2);
    expect(g[0].submissions[0].events).toHaveLength(2);
    expect(g[0].equipmentCount).toBe(3);
  });
});

describe("MonitorPage", () => {
  it("shows tab counts, Day group, expands to BCM codes, switches to receipts with outcome", async () => {
    setup();
    await waitFor(() => expect(screen.getByRole("tab", { name: "จ่าย (3)" })).toBeInTheDocument());
    expect(screen.getByRole("tab", { name: "รับ (1)" })).toBeInTheDocument();
    expect(screen.getByText(/Day/)).toBeInTheDocument();
    expect(screen.queryByText("BCM-1")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /ICU/ }));
    expect(screen.getByText("BCM-1")).toBeInTheDocument();
    expect(screen.getByText("BCM-2")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: "รับ (1)" }));
    expect(screen.getByText(/Night/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /ICU/ }));
    expect(screen.getByText("BCM-R1")).toBeInTheDocument();
    expect(screen.getByText("(ชำรุด)")).toBeInTheDocument();
  });

  it("filters by ward via type-ahead chip", async () => {
    setup();
    await waitFor(() => expect(screen.getByRole("tab", { name: "จ่าย (3)" })).toBeInTheDocument());
    await userEvent.type(screen.getByLabelText("ค้นหาหอผู้ป่วย"), "IC");
    await userEvent.click(await screen.findByRole("button", { name: "ICU" }));
    await waitFor(() =>
      expect(fetchMonitorEvents).toHaveBeenCalledWith(expect.objectContaining({ kind: "dispatch", ward_id: "w1" })),
    );
    await waitFor(() => expect(screen.getByRole("tab", { name: "จ่าย (1)" })).toBeInTheDocument());
  });

  it("renders the last-updated label and never renders HN", async () => {
    setup();
    await waitFor(() => expect(screen.getByTestId("monitor-updated").textContent).toMatch(/อัปเดตล่าสุด \d{2}:\d{2}:\d{2}/));
    expect(screen.queryByText(/HN/)).not.toBeInTheDocument();
  });
});
