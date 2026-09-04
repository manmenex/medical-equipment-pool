import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OperatorAutocomplete } from "@/components/OperatorAutocomplete";
import type { ReportOperatorOut } from "@/types";

const getOperatorOptions = vi.fn();
vi.mock("@/services/reports", () => ({
  getOperatorOptions: (...args: unknown[]) => getOperatorOptions(...args),
}));

afterEach(() => {
  vi.clearAllMocks();
});

function page(items: ReportOperatorOut[], nextCursor: string | null = null): {
  items: ReportOperatorOut[];
  next_cursor: string | null;
  total: number;
} {
  return { items, next_cursor: nextCursor, total: items.length };
}

const staff: ReportOperatorOut = { id: "op-1", display_name: "สมชาย ใจดี", is_active: true };
const inactiveStaff: ReportOperatorOut = { id: "op-2", display_name: "สมหญิง รักงาน", is_active: false };

describe("OperatorAutocomplete", () => {
  it("calls only GET /report-options/operators (via getOperatorOptions), never a user-management endpoint", async () => {
    getOperatorOptions.mockResolvedValue(page([staff]));
    render(<OperatorAutocomplete value={null} onChange={vi.fn()} />);

    await waitFor(() => expect(getOperatorOptions).toHaveBeenCalled());
    for (const call of getOperatorOptions.mock.calls) {
      expect(call[0]).not.toHaveProperty("employee_code");
    }
  });

  it("shows a loading indicator while the operator list is being fetched", async () => {
    getOperatorOptions.mockReturnValue(new Promise(() => {}));
    const user = userEvent.setup();
    render(<OperatorAutocomplete value={null} onChange={vi.fn()} />);

    await user.click(screen.getByRole("textbox"));
    expect(await screen.findByText("กำลังค้นหา...")).toBeInTheDocument();
  });

  it("shows an empty state when no operators match", async () => {
    getOperatorOptions.mockResolvedValue(page([]));
    const user = userEvent.setup();
    render(<OperatorAutocomplete value={null} onChange={vi.fn()} />);

    await user.click(screen.getByRole("textbox"));
    expect(await screen.findByText("ไม่พบผู้ปฏิบัติงาน")).toBeInTheDocument();
  });

  it("shows an error state when the lookup fails", async () => {
    getOperatorOptions.mockRejectedValue({
      isAxiosError: true,
      response: { data: { detail: "โหลดไม่สำเร็จ" } },
    });
    const user = userEvent.setup();
    render(<OperatorAutocomplete value={null} onChange={vi.fn()} />);

    await user.click(screen.getByRole("textbox"));
    expect(await screen.findByText("โหลดไม่สำเร็จ")).toBeInTheDocument();
  });

  it("performs incremental search: typing re-queries with the debounced query text", async () => {
    getOperatorOptions.mockResolvedValue(page([staff]));
    const user = userEvent.setup();
    render(<OperatorAutocomplete value={null} onChange={vi.fn()} />);

    await user.type(screen.getByRole("textbox"), "สมชาย");

    await waitFor(
      () => expect(getOperatorOptions).toHaveBeenCalledWith(expect.objectContaining({ q: "สมชาย" })),
      { timeout: 2000 }
    );
  });

  it("selecting an operator stores its id via onChange and displays display_name in the input", async () => {
    getOperatorOptions.mockResolvedValue(page([staff]));
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<OperatorAutocomplete value={null} onChange={onChange} />);

    await user.click(screen.getByRole("textbox"));
    const option = await screen.findByText("สมชาย ใจดี");
    await user.click(option);

    expect(onChange).toHaveBeenCalledWith(staff);
    expect(screen.getByRole("textbox")).toHaveValue("สมชาย ใจดี");
  });

  it("labels an inactive operator distinctly but still allows selecting them", async () => {
    getOperatorOptions.mockResolvedValue(page([inactiveStaff]));
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<OperatorAutocomplete value={null} onChange={onChange} />);

    await user.click(screen.getByRole("textbox"));
    expect(await screen.findByText("(ไม่ใช้งานแล้ว)")).toBeInTheDocument();

    await user.click(screen.getByText("สมหญิง รักงาน"));
    expect(onChange).toHaveBeenCalledWith(inactiveStaff);
  });

  it("supports pagination: a next_cursor shows โหลดเพิ่มเติม, which appends (never replaces) results", async () => {
    getOperatorOptions.mockResolvedValueOnce(page([staff], "cursor-2"));
    const user = userEvent.setup();
    render(<OperatorAutocomplete value={null} onChange={vi.fn()} />);

    await user.click(screen.getByRole("textbox"));
    await screen.findByText("สมชาย ใจดี");
    const loadMore = screen.getByRole("button", { name: "โหลดเพิ่มเติม" });

    getOperatorOptions.mockResolvedValueOnce(page([inactiveStaff], null));
    await user.click(loadMore);

    await waitFor(() => expect(screen.getByText("สมหญิง รักงาน")).toBeInTheDocument());
    // Appended, not replaced -- the first result must still be present.
    expect(screen.getByText("สมชาย ใจดี")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "โหลดเพิ่มเติม" })).not.toBeInTheDocument();
  });

  it("clearing a selection calls onChange(null) and empties the input", async () => {
    getOperatorOptions.mockResolvedValue(page([staff]));
    const onChange = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(<OperatorAutocomplete value={staff} onChange={onChange} />);

    expect(screen.getByRole("textbox")).toHaveValue("สมชาย ใจดี");
    await user.click(screen.getByRole("button", { name: "ล้างผู้ปฏิบัติงานที่เลือก" }));

    expect(onChange).toHaveBeenCalledWith(null);
    rerender(<OperatorAutocomplete value={null} onChange={onChange} />);
    expect(screen.getByRole("textbox")).toHaveValue("");
  });
});
