import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { UndoToast, formatCountdown } from "@/components/entry/UndoToast";

const undoTransaction = vi.fn();
vi.mock("@/services/borrow", () => ({ undoTransaction: (...a: unknown[]) => undoTransaction(...a) }));

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("UndoToast (D28 layer 2)", () => {
  it("formats the countdown as m:ss", () => {
    expect(formatCountdown(120)).toBe("2:00");
    expect(formatCountdown(30)).toBe("0:30");
    expect(formatCountdown(5)).toBe("0:05");
  });

  describe("countdown", () => {
    beforeEach(() => vi.useFakeTimers());

    it("counts down and hides itself when the time runs out", () => {
      const onClose = vi.fn();
      render(<UndoToast ids={["a"]} seconds={30} onClose={onClose} />);
      expect(screen.getByRole("button", { name: "บันทึกแล้ว · เลิกทำ (0:30)" })).toBeInTheDocument();
      act(() => void vi.advanceTimersByTime(10_000));
      expect(screen.getByRole("button", { name: "บันทึกแล้ว · เลิกทำ (0:20)" })).toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();
      act(() => void vi.advanceTimersByTime(21_000));
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("undoes each id and reports the ones that failed with the server message", async () => {
    undoTransaction
      .mockResolvedValueOnce({})
      .mockRejectedValueOnce({ isAxiosError: true, response: { data: { detail: "เกินเวลาเลิกทำ" } } });
    const onUndone = vi.fn();
    const user = userEvent.setup();
    render(<UndoToast ids={["a", "b"]} labels={["BCM-A", "BCM-B"]} seconds={120} onClose={vi.fn()} onUndone={onUndone} />);
    await user.click(screen.getByRole("button", { name: /เลิกทำ \(2:00\)/ }));
    await waitFor(() => expect(undoTransaction).toHaveBeenCalledTimes(2));
    expect(undoTransaction.mock.calls.map((c) => c[0])).toEqual(["a", "b"]);
    expect(await screen.findByText("เลิกทำแล้ว 1 รายการ")).toBeInTheDocument();
    expect(screen.getByText("✗ BCM-B: เกินเวลาเลิกทำ")).toBeInTheDocument();
    expect(onUndone).toHaveBeenCalledWith({ ok: 1, failedIds: ["b"] });
  });
});
