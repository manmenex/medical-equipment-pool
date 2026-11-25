import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { AxiosError } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HnField, HnIndicator, HnReveal, REVEAL_SECONDS, sanitizeHn } from "./HnField";

const revealHn = vi.fn();
vi.mock("@/services/borrow", () => ({ revealHn: (...a: unknown[]) => revealHn(...a) }));

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

function Harness({ initial = "" }: { initial?: string }) {
  const [hn, setHn] = useState(initial);
  return (
    <>
      <HnField value={hn} onChange={setHn} />
      <HnIndicator hn={hn} />
      <button type="button">other</button>
    </>
  );
}

describe("sanitizeHn", () => {
  it("keeps letters, digits, - and /, max 20", () => {
    expect(sanitizeHn(" HN 12-34/5!x ")).toBe("HN12-34/5x");
    expect(sanitizeHn("1".repeat(30))).toHaveLength(20);
  });
});

describe("HnField (dispatch, unsubmitted item)", () => {
  it("is optional: empty shows no indicator and no mask", () => {
    render(<Harness />);
    expect(screen.getByLabelText("HN ผู้ป่วย (ไม่บังคับ)")).toBeInTheDocument();
    expect(screen.queryByText("🔒HN")).not.toBeInTheDocument();
    expect(screen.queryByTestId("hn-masked")).not.toBeInTheDocument();
  });

  it("after entry shows 🔒HN and a mask, never the value, until 'แสดง HN' is clicked", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByLabelText("HN ผู้ป่วย (ไม่บังคับ)"), "HN123");
    expect(screen.getByLabelText("มี HN")).toBeInTheDocument(); // row indicator while typing
    await user.click(screen.getByRole("button", { name: "other" })); // leave the field
    expect(screen.getByTestId("hn-masked")).toHaveTextContent("●●●");
    expect(document.body.textContent).not.toContain("HN123");
    await user.click(screen.getByRole("button", { name: "แสดง HN" }));
    expect(screen.getByTestId("hn-value")).toHaveTextContent("HN123");
    await user.click(screen.getByRole("button", { name: "ซ่อน HN" }));
    expect(document.body.textContent).not.toContain("HN123");
  });

  it("auto-hides the revealed value after 30 seconds", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<Harness initial="HN777" />);
    await user.click(screen.getByRole("button", { name: "แสดง HN" }));
    expect(screen.getByTestId("hn-value")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime((REVEAL_SECONDS - 1) * 1000);
    });
    expect(screen.getByTestId("hn-value")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(1500);
    });
    expect(screen.queryByTestId("hn-value")).not.toBeInTheDocument();
    expect(screen.getByTestId("hn-masked")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("HN777");
  });

  it("can be edited again and cleared (back to no indicator)", async () => {
    const user = userEvent.setup();
    render(<Harness initial="HN1" />);
    await user.click(screen.getByRole("button", { name: "แก้ไข HN" }));
    const input = screen.getByLabelText("HN ผู้ป่วย (ไม่บังคับ)");
    await user.clear(input);
    expect(screen.queryByLabelText("มี HN")).not.toBeInTheDocument();
  });

  it("never persists the value to browser storage", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByLabelText("HN ผู้ป่วย (ไม่บังคับ)"), "SECRET99");
    expect(JSON.stringify({ ...localStorage })).not.toContain("SECRET99");
    expect(JSON.stringify({ ...sessionStorage })).not.toContain("SECRET99");
  });
});

describe("HnReveal (existing transaction)", () => {
  beforeEach(() => {
    revealHn.mockResolvedValue("HN-555");
  });

  it("shows 🔒HN and a mask without calling the server", () => {
    render(<HnReveal transactionId="t1" />);
    expect(screen.getByText("🔒HN")).toBeInTheDocument();
    expect(screen.getByTestId("hn-masked")).toBeInTheDocument();
    expect(revealHn).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toContain("HN-555");
  });

  it("calls reveal-hn on click, shows the value, and hides it after 30 seconds", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<HnReveal transactionId="t1" />);
    await user.click(screen.getByRole("button", { name: "แสดง HN" }));
    expect(revealHn).toHaveBeenCalledWith("t1");
    expect(await screen.findByTestId("hn-value")).toHaveTextContent("HN-555");
    act(() => {
      vi.advanceTimersByTime(REVEAL_SECONDS * 1000 + 100);
    });
    expect(screen.queryByTestId("hn-value")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("HN-555");
    // Revealing again is a fresh, separately audited request.
    await user.click(screen.getByRole("button", { name: "แสดง HN" }));
    await waitFor(() => expect(revealHn.mock.calls).toEqual([["t1"], ["t1"]]));
  });

  it("can be hidden manually and drops the value from memory", async () => {
    const user = userEvent.setup();
    render(<HnReveal transactionId="t1" />);
    await user.click(screen.getByRole("button", { name: "แสดง HN" }));
    await screen.findByTestId("hn-value");
    await user.click(screen.getByRole("button", { name: "ซ่อน HN" }));
    expect(screen.queryByTestId("hn-value")).not.toBeInTheDocument();
  });

  it("explains an unavailable key and shows no value", async () => {
    revealHn.mockImplementation(() =>
      Promise.reject(
      new AxiosError("x", "503", undefined, undefined, {
        status: 503,
        data: { code: "HN_UNAVAILABLE", detail: "x" },
        headers: {},
        statusText: "",
        config: {} as never,
      } as never),
      ),
    );
    const user = userEvent.setup();
    render(<HnReveal transactionId="t1" />);
    await user.click(screen.getByRole("button", { name: "แสดง HN" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("HN ใช้งานไม่ได้");
    expect(screen.queryByTestId("hn-value")).not.toBeInTheDocument();
  });
});
