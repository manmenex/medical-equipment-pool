import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AddHnAction } from "@/components/entry/AddHnAction";

const addHn = vi.fn();
const apiErrorCode = vi.fn();

vi.mock("@/services/borrow", () => ({ addHn: (...a: unknown[]) => addHn(...a), revealHn: vi.fn() }));
vi.mock("@/services/api", () => ({ apiErrorCode: (e: unknown) => apiErrorCode(e) }));

afterEach(() => vi.clearAllMocks());

describe("AddHnAction", () => {
  it("opens a masked input, sanitizes, saves the HN and reports success", async () => {
    const user = userEvent.setup();
    const onAdded = vi.fn();
    addHn.mockResolvedValue({ id: "t1", has_hn: true });
    render(<AddHnAction transactionId="t1" onAdded={onAdded} />);

    await user.click(screen.getByRole("button", { name: "เพิ่ม HN" }));
    const input = screen.getByLabelText("HN ผู้ป่วย");
    expect(input).toHaveAttribute("type", "password"); // masked while typing
    expect(screen.getByRole("button", { name: "บันทึก HN" })).toBeDisabled();

    await user.type(input, "HN 123/66!");
    expect(input).toHaveValue("HN123/66");
    await user.click(screen.getByRole("button", { name: "บันทึก HN" }));

    await waitFor(() => expect(addHn).toHaveBeenCalledWith("t1", "HN123/66"));
    await waitFor(() => expect(onAdded).toHaveBeenCalledTimes(1));
    // Back to the button; the typed value is gone.
    expect(screen.getByRole("button", { name: "เพิ่ม HN" })).toBeInTheDocument();
    expect(screen.queryByLabelText("HN ผู้ป่วย")).toBeNull();
    expect(document.body.textContent).not.toContain("HN123/66");
  });

  it("shows a clear message when an HN already exists and clears the typed value", async () => {
    const user = userEvent.setup();
    addHn.mockRejectedValue(new Error("409"));
    apiErrorCode.mockReturnValue("HN_ALREADY_RECORDED");
    const onAdded = vi.fn();
    render(<AddHnAction transactionId="t1" onAdded={onAdded} />);
    await user.click(screen.getByRole("button", { name: "เพิ่ม HN" }));
    await user.type(screen.getByLabelText("HN ผู้ป่วย"), "123456");
    await user.click(screen.getByRole("button", { name: "บันทึก HN" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("มี HN แล้ว");
    expect(screen.getByLabelText("HN ผู้ป่วย")).toHaveValue("");
    expect(onAdded).not.toHaveBeenCalled();
  });

  it("cancel discards the input", async () => {
    const user = userEvent.setup();
    render(<AddHnAction transactionId="t1" />);
    await user.click(screen.getByRole("button", { name: "เพิ่ม HN" }));
    await user.type(screen.getByLabelText("HN ผู้ป่วย"), "999");
    await user.click(screen.getByRole("button", { name: "ยกเลิก" }));
    expect(addHn).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "เพิ่ม HN" }));
    expect(screen.getByLabelText("HN ผู้ป่วย")).toHaveValue("");
  });
});
