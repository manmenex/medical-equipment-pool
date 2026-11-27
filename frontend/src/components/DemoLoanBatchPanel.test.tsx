import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DemoLoanBatchPanel } from "@/components/DemoLoanBatchPanel";
import type { DemoLoanBatchResult } from "@/services/equipment";

const registerDemoLoanBatch = vi.fn();
const listCategories = vi.fn();

vi.mock("@/services/equipment", () => ({
  registerDemoLoanBatch: (...a: unknown[]) => registerDemoLoanBatch(...a),
}));
vi.mock("@/services/masterData", () => ({ listCategories: (...a: unknown[]) => listCategories(...a) }));

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <DemoLoanBatchPanel />
    </QueryClientProvider>,
  );
}

async function fillShared() {
  await screen.findByRole("option", { name: "Infusion Pump" });
  await userEvent.selectOptions(screen.getByLabelText("หมวดหมู่"), "cat-1");
  await userEvent.type(screen.getByLabelText("เจ้าของเครื่อง"), "Acme Co.");
}

// userEvent.paste so tabs/newlines reach the textarea exactly as a paste would.
async function paste(text: string) {
  await userEvent.click(screen.getByLabelText("วาง Serial Number"));
  await userEvent.paste(text);
  await userEvent.click(screen.getByRole("button", { name: /เพิ่มลงตาราง/ }));
}

function result(over: Partial<DemoLoanBatchResult>): DemoLoanBatchResult {
  return { dry_run: true, valid: true, committed: false, total: 0, created_count: 0, rows: [], created: [], ...over };
}

beforeEach(() => {
  listCategories.mockResolvedValue([{ id: "cat-1", name: "Infusion Pump" }]);
});
afterEach(() => vi.clearAllMocks());

describe("DemoLoanBatchPanel (Roadmap PR33)", () => {
  it("turns pasted serials into rows with charger/clamp checked by default", async () => {
    renderPanel();
    await paste("SN-1\nSN-2\n\nSN-3");
    expect(screen.getByLabelText("Serial แถว 1")).toHaveValue("SN-1");
    expect(screen.getByLabelText("Serial แถว 3")).toHaveValue("SN-3");
    expect(screen.queryByLabelText("Serial แถว 4")).not.toBeInTheDocument();
    for (const i of [1, 2, 3]) {
      expect(screen.getByLabelText(`มีสายชาร์จ แถว ${i}`)).toBeChecked();
      expect(screen.getByLabelText(`มี Clamp แถว ${i}`)).toBeChecked();
    }
  });

  it("keeps validate/save disabled until shared fields and rows are present", async () => {
    renderPanel();
    expect(screen.getByRole("button", { name: "ตรวจสอบ (dry run)" })).toBeDisabled();
    await paste("SN-1");
    expect(screen.getByRole("button", { name: "ตรวจสอบ (dry run)" })).toBeDisabled(); // no category/company yet
    await fillShared();
    expect(screen.getByRole("button", { name: "ตรวจสอบ (dry run)" })).toBeEnabled();
  });

  it("dry run sends dry_run=true with per-row accessories and shows per-row errors without saving", async () => {
    registerDemoLoanBatch.mockResolvedValue(
      result({
        valid: false,
        total: 3,
        rows: [
          { index: 0, serial_number: "SN-1", errors: [], messages: [] },
          { index: 1, serial_number: "SN-1", errors: ["duplicate_in_batch"], messages: [] },
          { index: 2, serial_number: "SN-9", errors: ["duplicate_in_db"], messages: [] },
        ],
      }),
    );
    renderPanel();
    await fillShared();
    await paste("SN-1\nSN-1\nSN-9");
    await userEvent.click(screen.getByLabelText("มีสายชาร์จ แถว 2")); // uncheck
    await userEvent.click(screen.getByRole("button", { name: "ตรวจสอบ (dry run)" }));

    await waitFor(() => expect(registerDemoLoanBatch).toHaveBeenCalledTimes(1));
    const body = registerDemoLoanBatch.mock.calls[0][0];
    expect(body.dry_run).toBe(true);
    expect(body.shared).toMatchObject({ category_id: "cat-1", equipment_source: "demo", owner_company: "Acme Co." });
    expect(body.items).toEqual([
      { serial_number: "SN-1", has_charger: true, has_clamp: true },
      { serial_number: "SN-1", has_charger: false, has_clamp: true },
      { serial_number: "SN-9", has_charger: true, has_clamp: true },
    ]);

    expect(await screen.findByText(/ซ้ำกับแถวอื่นในชุดนี้/)).toBeInTheDocument();
    expect(screen.getByText(/มี Serial นี้ในระบบแล้ว/)).toBeInTheDocument();
    expect(screen.getByText(/พบข้อผิดพลาด 2 แถว/)).toBeInTheDocument();
    // Rows stay so the operator can fix them; nothing was committed.
    expect(screen.getByLabelText("Serial แถว 1")).toBeInTheDocument();
  });

  it("a valid dry run prompts to save; saving sends dry_run=false and clears the table on success", async () => {
    registerDemoLoanBatch
      .mockResolvedValueOnce(result({ valid: true, total: 2, rows: [] }))
      .mockResolvedValueOnce(result({ dry_run: false, valid: true, committed: true, total: 2, created_count: 2 }));
    renderPanel();
    await fillShared();
    await userEvent.click(screen.getByLabelText("ยืม"));
    await paste("A\nB");
    await userEvent.click(screen.getByRole("button", { name: "ตรวจสอบ (dry run)" }));
    expect(await screen.findByText(/ตรวจสอบผ่านทั้ง 2 แถว/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /บันทึกทั้งชุด/ }));
    await waitFor(() => expect(registerDemoLoanBatch).toHaveBeenCalledTimes(2));
    expect(registerDemoLoanBatch.mock.calls[1][0]).toMatchObject({ dry_run: false, shared: { equipment_source: "loan" } });
    expect(await screen.findByText("บันทึกสำเร็จ 2 เครื่อง")).toBeInTheDocument();
    expect(screen.queryByLabelText("Serial แถว 1")).not.toBeInTheDocument();
  });

  it("a commit rejected for row errors keeps the rows and reports nothing was saved", async () => {
    registerDemoLoanBatch.mockResolvedValue(
      result({
        dry_run: false,
        valid: false,
        committed: false,
        total: 1,
        rows: [{ index: 0, serial_number: "", errors: ["blank"], messages: [] }],
      }),
    );
    renderPanel();
    await fillShared();
    await paste("X");
    await userEvent.click(screen.getByRole("button", { name: /บันทึกทั้งชุด/ }));
    expect(await screen.findByText(/ยังไม่ได้บันทึกอะไร/)).toBeInTheDocument();
    expect(screen.getByLabelText("Serial แถว 1")).toBeInTheDocument();
  });

  it("editing a row invalidates a stale validation result", async () => {
    registerDemoLoanBatch.mockResolvedValue(
      result({ valid: false, total: 1, rows: [{ index: 0, serial_number: "X", errors: ["duplicate_in_db"], messages: [] }] }),
    );
    renderPanel();
    await fillShared();
    await paste("X");
    await userEvent.click(screen.getByRole("button", { name: "ตรวจสอบ (dry run)" }));
    expect(await screen.findByText(/มี Serial นี้ในระบบแล้ว/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Serial แถว 1"), "2");
    expect(screen.queryByText(/มี Serial นี้ในระบบแล้ว/)).not.toBeInTheDocument();
  });
});
