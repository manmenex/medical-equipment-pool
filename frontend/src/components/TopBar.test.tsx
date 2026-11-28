import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DbStatusLight } from "./DbStatusLight";
import { TopBarClock, formatBangkokClock } from "./TopBarClock";

function setOnline(v: boolean) {
  Object.defineProperty(navigator, "onLine", { value: v, configurable: true });
}
const flush = async () => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
};

describe("DbStatusLight", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setOnline(true);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("green when ready", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200 }));
    render(<DbStatusLight />);
    await flush();
    const el = screen.getByTestId("db-status");
    expect(el).toHaveAttribute("data-state", "online");
    expect(el).toHaveTextContent("ออนไลน์");
    expect(el).toHaveAttribute("title");
    expect(el.getAttribute("aria-label")).toContain("ออนไลน์");
  });

  it("amber when browser offline, without calling the server", async () => {
    setOnline(false);
    const f = vi.fn();
    vi.stubGlobal("fetch", f);
    render(<DbStatusLight />);
    await flush();
    expect(screen.getByTestId("db-status")).toHaveAttribute("data-state", "offline");
    expect(screen.getByText("ออฟไลน์")).toBeInTheDocument();
    expect(f).not.toHaveBeenCalled();
  });

  it("red on 503 and on network failure while online", async () => {
    const f = vi.fn().mockResolvedValue({ ok: false, status: 503 });
    vi.stubGlobal("fetch", f);
    render(<DbStatusLight />);
    await flush();
    expect(screen.getByText("ฐานข้อมูลขัดข้อง")).toBeInTheDocument();
    f.mockRejectedValue(new TypeError("fail"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(screen.getByTestId("db-status")).toHaveAttribute("data-state", "db_down");
  });

  it("re-polls every 30 s and reacts to offline/online events", async () => {
    const f = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    vi.stubGlobal("fetch", f);
    render(<DbStatusLight />);
    await flush();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(f).toHaveBeenCalledTimes(2);
    act(() => {
      setOnline(false);
      window.dispatchEvent(new Event("offline"));
    });
    expect(screen.getByTestId("db-status")).toHaveAttribute("data-state", "offline");
    setOnline(true);
    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    await flush();
    expect(screen.getByTestId("db-status")).toHaveAttribute("data-state", "online");
  });
});

describe("TopBarClock", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("formats Buddhist-era date in Asia/Bangkok", () => {
    expect(formatBangkokClock(new Date("2026-11-28T01:45:00Z"))).toEqual({
      date: "28/11/2569",
      time: "08:45",
    });
    expect(formatBangkokClock(new Date("2026-12-31T17:05:00Z"))).toEqual({
      date: "01/01/2570",
      time: "00:05",
    });
  });

  it("renders full text, ticks every 30 s, and has a compact HH:mm part", () => {
    vi.setSystemTime(new Date("2026-11-28T01:45:00Z"));
    render(<TopBarClock />);
    expect(screen.getByTestId("top-bar-clock")).toHaveTextContent("28/11/2569 08:45");
    act(() => {
      vi.advanceTimersByTime(30_000 * 2);
    });
    expect(screen.getByTestId("clock-time")).toHaveTextContent("08:46");
    expect(screen.getByTestId("clock-date").className).toMatch(/hidden\s+sm:inline/);
    expect(screen.getByTestId("clock-time").className).not.toMatch(/hidden/);
  });
});
