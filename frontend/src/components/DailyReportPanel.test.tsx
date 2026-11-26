import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DailyReportPanel } from "@/components/DailyReportPanel";

const downloadDailySummary = vi.fn();
const printDailyForm = vi.fn();

vi.mock("@/services/dailyReport", () => ({
  DEFAULT_GRACE_MINUTES: 60,
  MAX_GRACE_MINUTES: 240,
  downloadDailySummary: (...a: unknown[]) => downloadDailySummary(...a),
  printDailyForm: (...a: unknown[]) => printDailyForm(...a),
}));

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("DailyReportPanel", () => {
  it("defaults to the current business date and 60 grace minutes and wires the three buttons", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 25, 3, 0)); // before 08:00 -> business date is the 24th
    downloadDailySummary.mockResolvedValue(undefined);
    printDailyForm.mockResolvedValue(undefined);
    render(<DailyReportPanel />);
    vi.useRealTimers();
    const user = userEvent.setup();

    expect(screen.getByLabelText("วันที่รายงาน")).toHaveValue("2026-11-24");
    expect(screen.getByLabelText(/ช่วงเวลายืดหยุ่นรอบเวร/)).toHaveValue(60);

    await user.click(screen.getByRole("button", { name: "ดาวน์โหลด Excel" }));
    expect(downloadDailySummary).toHaveBeenCalledWith("2026-11-24", 60);
    await user.click(screen.getByRole("button", { name: "พิมพ์ฟอร์มส่ง" }));
    expect(printDailyForm).toHaveBeenLastCalledWith("2026-11-24", "dispatch", 60, "day");
    await user.click(screen.getByRole("button", { name: "พิมพ์ฟอร์มรับ" }));
    expect(printDailyForm).toHaveBeenLastCalledWith("2026-11-24", "receipt", 60, "day");
  });

  it("prints forms for the chosen shift and offers the combined summary", async () => {
    downloadDailySummary.mockResolvedValue(undefined);
    printDailyForm.mockResolvedValue(undefined);
    render(<DailyReportPanel />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("radio", { name: "กะกลางคืน" }));
    await user.click(screen.getByRole("button", { name: "พิมพ์ฟอร์มส่ง" }));
    expect(printDailyForm).toHaveBeenLastCalledWith(expect.any(String), "dispatch", 60, "night");
    await user.click(screen.getByRole("radio", { name: "ทั้งสองกะ" }));
    await user.click(screen.getByRole("button", { name: "พิมพ์ฟอร์มรับ" }));
    expect(printDailyForm).toHaveBeenLastCalledWith(expect.any(String), "receipt", 60, "both");
    await user.click(screen.getByRole("button", { name: /สรุปรวมยอด/ }));
    await waitFor(() => expect(printDailyForm).toHaveBeenLastCalledWith(expect.any(String), "both", 60, "day"));
    expect(downloadDailySummary).toHaveBeenCalledTimes(1);
  });

  it("sends a changed date and grace, allows 0 (strict), and blocks invalid grace", async () => {
    downloadDailySummary.mockResolvedValue(undefined);
    render(<DailyReportPanel />);
    const user = userEvent.setup();
    const grace = screen.getByLabelText(/ช่วงเวลายืดหยุ่นรอบเวร/);

    await user.clear(grace);
    await user.type(grace, "0");
    await user.click(screen.getByRole("button", { name: "ดาวน์โหลด Excel" }));
    expect(downloadDailySummary).toHaveBeenCalledWith(expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/), 0);

    await user.clear(grace);
    await user.type(grace, "999");
    expect(screen.getByRole("alert")).toHaveTextContent("0-240");
    expect(screen.getByRole("button", { name: "ดาวน์โหลด Excel" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "พิมพ์ฟอร์มส่ง" })).toBeDisabled();
  });

  it("shows an error when generation fails", async () => {
    downloadDailySummary.mockRejectedValue(new Error("boom"));
    render(<DailyReportPanel />);
    await userEvent.setup().click(screen.getByRole("button", { name: "ดาวน์โหลด Excel" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("สร้างรายงานไม่สำเร็จ"));
  });
});
