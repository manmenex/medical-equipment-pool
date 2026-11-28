import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { registerFormDirty, resetAppUpdate, setUpdateReady } from "@/offline/appUpdate";
import { RefreshButton } from "./RefreshButton";

function setReg(reg: unknown) {
  Object.defineProperty(navigator, "serviceWorker", {
    value: { getRegistration: vi.fn().mockResolvedValue(reg) },
    configurable: true,
  });
}
function setOnline(v: boolean) {
  Object.defineProperty(navigator, "onLine", { value: v, configurable: true });
}

vi.mock("@/offline/offlineStore", () => ({
  listAllActiveOutboxCount: vi.fn().mockResolvedValue(0),
}));

describe("RefreshButton", () => {
  it("dirty form: cancel keeps page, confirm proceeds", async () => {
    const waiting = { postMessage: vi.fn() };
    const update = vi.fn().mockResolvedValue(undefined);
    setReg({ update, waiting });
    const reload = vi.fn();
    registerFormDirty(Symbol("f"), true);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<RefreshButton reload={reload} />);
    await act(async () => {
      fireEvent.click(screen.getByTestId("refresh-button"));
    });
    expect(confirm).toHaveBeenCalledWith("มีข้อมูลที่ยังไม่บันทึก ต้องการรีเฟรชหรือไม่?");
    expect(reload).not.toHaveBeenCalled();
    expect(waiting.postMessage).not.toHaveBeenCalled();
    expect(update).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    await act(async () => {
      fireEvent.click(screen.getByTestId("refresh-button"));
    });
    expect(waiting.postMessage).toHaveBeenCalled();
    expect(reload).toHaveBeenCalledTimes(1);
  });

  beforeEach(() => {
    resetAppUpdate();
    setOnline(true);
  });
  afterEach(() => vi.restoreAllMocks());

  it("updates the registration then reloads", async () => {
    const update = vi.fn().mockResolvedValue(undefined);
    setReg({ update, waiting: null });
    const reload = vi.fn();
    render(<RefreshButton reload={reload} />);
    const b = screen.getByTestId("refresh-button");
    expect(b).toHaveAttribute("aria-label", "รีเฟรช");
    expect(b.className).toContain("h-10");
    expect(b.className).toContain("w-10");
    await act(async () => {
      fireEvent.click(b);
    });
    expect(update).toHaveBeenCalled();
    expect(reload).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("refresh-badge")).toBeNull();
  });

  it("shows badge and applies the waiting update via updateSW", async () => {
    setReg({ update: vi.fn().mockResolvedValue(undefined), waiting: null });
    const apply = vi.fn().mockResolvedValue(undefined);
    const reload = vi.fn();
    render(<RefreshButton reload={reload} />);
    act(() => setUpdateReady(apply));
    expect(screen.getByTestId("refresh-badge")).toBeInTheDocument();
    expect(screen.getByTestId("refresh-button")).toHaveAttribute(
      "aria-label",
      "มีเวอร์ชันใหม่ กดเพื่ออัปเดต",
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId("refresh-button"));
    });
    expect(apply).toHaveBeenCalled();
    expect(reload).not.toHaveBeenCalled();
  });

  it("badge from a waiting worker; offline skips update() and still reloads", async () => {
    setOnline(false);
    const update = vi.fn();
    setReg({ update, waiting: { postMessage: vi.fn() } });
    const reload = vi.fn();
    render(<RefreshButton reload={reload} />);
    await act(async () => {});
    expect(screen.getByTestId("refresh-badge")).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByTestId("refresh-button"));
    });
    expect(update).not.toHaveBeenCalled();
    expect(reload).toHaveBeenCalled();
  });

  it("offline tooltip", async () => {
    setOnline(false);
    setReg(undefined);
    render(<RefreshButton reload={vi.fn()} />);
    await act(async () => {});
    expect(screen.getByTestId("refresh-button").title).toContain("ออฟไลน์");
  });
});
