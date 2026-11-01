import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SyncStatsPanel } from "@/components/SyncStatsPanel";
import { SyncTimelinePanel } from "@/components/SyncTimelinePanel";
import type { EquipmentTimeline, TimelineEvent } from "@/services/syncSequence";

const fetchEquipmentTimeline = vi.fn();
const applySequence = vi.fn();
const fetchCollisionStats = vi.fn();
const downloadCollisionCsv = vi.fn();
vi.mock("@/services/syncSequence", () => ({
  fetchEquipmentTimeline: (...a: unknown[]) => fetchEquipmentTimeline(...a),
  applySequence: (...a: unknown[]) => applySequence(...a),
  fetchCollisionStats: (...a: unknown[]) => fetchCollisionStats(...a),
  downloadCollisionCsv: (...a: unknown[]) => downloadCollisionCsv(...a),
}));

function ev(over: Partial<TimelineEvent>): TimelineEvent {
  return {
    source: "op",
    kind: "dispatch",
    at: "2026-10-20T01:00:00Z",
    band_s: 30,
    order_uncertain: false,
    selectable: true,
    op_id: "op-a",
    status: "conflict",
    result_code: "EQUIPMENT_NOT_AVAILABLE",
    operator: { id: "u1", full_name: "สมชาย" },
    ward_name: "ICU",
    ...over,
  };
}

const timeline = (events: TimelineEvent[]): EquipmentTimeline => ({
  equipment: { id: "e1", bcm_code: "BCM1", equipment_name: "Pump", status: "available_at_pool" },
  server_time: "2026-10-20T02:00:00Z",
  events,
});

function apiError(status: number, code: string) {
  return { isAxiosError: true, response: { status, data: { code, detail: "x" } } };
}

function renderPanel(onChanged = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <SyncTimelinePanel equipmentId="e1" onClose={vi.fn()} onChanged={onChanged} />
    </QueryClientProvider>,
  );
  return onChanged;
}

const events = [
  ev({ source: "transaction", selectable: false, op_id: null, at: "2026-10-20T00:00:00Z", band_s: 0 }),
  ev({ op_id: "op-a", at: "2026-10-20T01:00:00Z", order_uncertain: true }),
  ev({ op_id: "op-b", kind: "receipt", status: "pending", at: "2026-10-20T01:10:00Z" }),
];

beforeEach(() => {
  fetchEquipmentTimeline.mockReset().mockResolvedValue(timeline(events));
  applySequence.mockReset().mockResolvedValue({ dry_run: false, steps: [{ op_id: "op-a", ok: true }, { op_id: "op-b", ok: true }], failed: null, remaining: [] });
  fetchCollisionStats.mockReset();
  downloadCollisionCsv.mockReset().mockResolvedValue(undefined);
});

describe("SyncTimelinePanel", () => {
  it("renders events; only review ops are selectable; flags uncertain order", async () => {
    renderPanel();
    expect(await screen.findAllByTestId("timeline-event")).toHaveLength(3);
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
    expect(screen.getByText("ลำดับไม่แน่ชัด")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Apply sequence/ })).toBeDisabled();
    expect(applySequence).not.toHaveBeenCalled();
  });

  it("confirms the ordered list in timeline order, then applies", async () => {
    const onChanged = renderPanel();
    const boxes = await screen.findAllByRole("checkbox");
    fireEvent.click(boxes[1]); // click later op first: order still follows the timeline
    fireEvent.click(boxes[0]);
    fireEvent.click(screen.getByRole("button", { name: /Apply sequence/ }));
    const dialog = screen.getByRole("dialog");
    const items = within(dialog).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("เบิก");
    expect(items[1]).toHaveTextContent("รับคืน");
    expect(applySequence).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "ยืนยัน" }));
    await waitFor(() => expect(applySequence).toHaveBeenCalledWith("e1", ["op-a", "op-b"]));
    expect(await screen.findByText(/บันทึกครบ 2 รายการ/)).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalled();
  });

  it("reports a partial run that stopped at the first failure", async () => {
    applySequence.mockResolvedValue({
      dry_run: false,
      steps: [{ op_id: "op-a", ok: true }],
      failed: { op_id: "op-b", ok: false, code: "TRANSACTION_NOT_FOUND" },
      remaining: [],
    });
    renderPanel();
    for (const b of await screen.findAllByRole("checkbox")) fireEvent.click(b);
    fireEvent.click(screen.getByRole("button", { name: /Apply sequence/ }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "ยืนยัน" }));
    expect(await screen.findByText(/หยุดที่รายการที่ 2/)).toBeInTheDocument();
  });

  it("handles 409 by refreshing and closing the dialog", async () => {
    applySequence.mockRejectedValue(apiError(409, "SYNC_OP_NOT_RESOLVABLE"));
    const onChanged = renderPanel();
    fireEvent.click((await screen.findAllByRole("checkbox"))[0]);
    fireEvent.click(screen.getByRole("button", { name: /Apply sequence/ }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "ยืนยัน" }));
    expect(await screen.findByText(/ถูกดำเนินการไปแล้ว/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(onChanged).toHaveBeenCalled();
  });

  it("disables confirm while in flight (no double submit)", async () => {
    let release: () => void = () => undefined;
    applySequence.mockReturnValue(new Promise((r) => (release = () => r({ dry_run: false, steps: [], failed: null, remaining: [] }))));
    renderPanel();
    fireEvent.click((await screen.findAllByRole("checkbox"))[0]);
    fireEvent.click(screen.getByRole("button", { name: /Apply sequence/ }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "ยืนยัน" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "กำลังดำเนินการ..." })).toBeDisabled());
    expect(applySequence).toHaveBeenCalledTimes(1);
    release();
  });
});

describe("SyncStatsPanel", () => {
  it("shows stats and downloads the CSV", async () => {
    fetchCollisionStats.mockResolvedValue({
      range_from: "a", range_to: "b", total_conflicts: 7, by_result_code: { EQUIPMENT_NOT_AVAILABLE: 5 },
      by_status: {}, by_day: {}, truncated: false,
      groups: {
        equipment_with_multiple_conflicts: 2, cross_device: 1, by_outcome: {}, agreement_rate: 0.5,
        would_have_auto_sequenced: { conditions_met: 1, resolved_same_order: 1, resolved_differently: 0, agreement_rate: 1 },
      },
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={qc}><SyncStatsPanel /></QueryClientProvider>);
    expect(await screen.findByText("7")).toBeInTheDocument();
    expect(screen.getByText("50.0%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "ดาวน์โหลด CSV" }));
    await waitFor(() => expect(downloadCollisionCsv).toHaveBeenCalled());
  });
});
