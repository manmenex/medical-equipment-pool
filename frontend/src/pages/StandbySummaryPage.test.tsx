import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StandbySummaryPage } from "@/pages/StandbySummaryPage";
import type { StandbyCutoff, StandbyField, StandbySummary } from "@/services/standbySummary";

const fetchStandbySummary = vi.fn();
const fetchStandbyText = vi.fn();
const saveStandbyOverride = vi.fn();
const saveStandbyBaseline = vi.fn();
const downloadDailySummary = vi.fn();
let mockRole = "equipment_pool_staff";

vi.mock("@/hooks/useAuth", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useAuth")>("@/hooks/useAuth");
  return {
    ...actual,
    useAuth: () => ({ user: { id: "u", role: mockRole }, isAuthenticated: true, isLoading: false }),
  };
});
vi.mock("@/services/standbySummary", () => ({
  fetchStandbySummary: (...a: unknown[]) => fetchStandbySummary(...a),
  fetchStandbyText: (...a: unknown[]) => fetchStandbyText(...a),
  saveStandbyOverride: (...a: unknown[]) => saveStandbyOverride(...a),
  saveStandbyBaseline: (...a: unknown[]) => saveStandbyBaseline(...a),
}));
vi.mock("@/services/dailyReport", () => ({
  DEFAULT_GRACE_MINUTES: 60,
  downloadDailySummary: (...a: unknown[]) => downloadDailySummary(...a),
}));

const field = (key: string, label: string, system: number | null, override: number | null = null): StandbyField => ({
  key,
  label,
  system_value: system,
  override_value: override,
  effective_value: override ?? system,
});

function summary(cutoff: StandbyCutoff, over: Partial<Record<string, number | null>> = {}): StandbySummary {
  const w5a = cutoff === "night" ? 2 : 1;
  return {
    date: "2026-07-28",
    cutoff,
    cutoff_at: "2026-07-28T01:00:00Z",
    business_day_start: "2026-07-27T13:00:00Z",
    infusion: {
      categories: ["Infusion Pump"],
      wards: [field("ward:W5A", "W5A", w5a, over["ward:W5A"] ?? null), field("ward:W5B", "W5B", 0)],
      bme_devices: field("bme_devices", "BME", 3),
      chargers: field("chargers", "สายชาร์จ", 8),
      clamps: field("clamps", "Clamp", 4),
      ready: field("ready", "พร้อมใช้งาน", 3),
      baseline: { chargers: 10, clamps: 8, set_at: "2026-07-27T01:00:00Z" },
    },
    pneumatic: {
      categories: ["Pneumatic Pump"],
      in_use: field("pneumatic_in_use", "เครื่องที่ใช้งานอยู่", 1),
      returned: field("pneumatic_returned", "รับคืนเครื่องวันนี้", 1),
    },
    approximations: ["ค่าประมาณ"],
  };
}

function setup() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <StandbySummaryPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockRole = "equipment_pool_staff";
  fetchStandbySummary.mockImplementation(async (_d: string, c: StandbyCutoff) => summary(c));
  fetchStandbyText.mockResolvedValue("Infusion pump standby\n28/07/2026\nW5A = 2 เครื่อง");
});
afterEach(() => vi.clearAllMocks());

// The page renders both the md+ table and the <md list (CSS toggles them), so
// ward inputs exist twice in jsdom; desktop-oriented tests scope to the table.
const tableInput = (name: string) => within(screen.getByTestId("standby-table")).getByRole("spinbutton", { name });
const findTableInput = async (name: string) => {
  await screen.findByTestId("standby-table");
  return tableInput(name);
};

describe("StandbySummaryPage", () => {
  it("defaults to the Night (08:00) summary and the toggle switches the cut-off", async () => {
    const user = userEvent.setup();
    setup();
    expect(await findTableInput("Stand By W5A")).toHaveValue(2);
    expect(fetchStandbySummary).toHaveBeenLastCalledWith(expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/), "night");
    expect(screen.getByRole("button", { name: "สรุปกะ Night (08:00)" })).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: "สรุปกะ Day (20:00)" }));
    await waitFor(() => expect(tableInput("Stand By W5A")).toHaveValue(1));
    expect(fetchStandbySummary).toHaveBeenLastCalledWith(expect.any(String), "day");
    expect(fetchStandbyText).toHaveBeenLastCalledWith(expect.any(String), "day");
    expect(screen.getByRole("button", { name: "สรุปกะ Day (20:00)" })).toHaveAttribute("aria-pressed", "true");
  });

  it("groups ward rows by dispense mode / treatment type like the Excel", async () => {
    setup();
    expect(await screen.findByText("รูปแบบการจ่ายเครื่อง")).toBeInTheDocument();
    expect(screen.getByText("ประเภทการรักษา")).toBeInTheDocument();
    expect(screen.getByText("แผนก")).toBeInTheDocument();
  });

  it("shows all editable fields", async () => {
    setup();
    expect(await findTableInput("Stand By W5B")).toBeEnabled();
    for (const name of ["เครื่องใหม่ (เครื่อง)", "สายชาร์จ", "Clamp", "พร้อมใช้งาน (เครื่อง)", "เครื่องที่ใช้งานอยู่", "รับคืนเครื่องวันนี้"]) {
      expect(await screen.findByRole("spinbutton", { name })).toBeEnabled();
    }
  });

  it("saves an edit as an override, shows the system value hint, and resets it", async () => {
    const user = userEvent.setup();
    saveStandbyOverride.mockResolvedValueOnce(summary("night", { "ward:W5A": 5 }));
    setup();
    const input = await findTableInput("Stand By W5A");
    expect(screen.queryByTestId("hint-ward:W5A")).toBeNull();

    await user.clear(input);
    await user.type(input, "5");
    await user.tab();
    await waitFor(() =>
      expect(saveStandbyOverride).toHaveBeenCalledWith(expect.any(String), "night", "ward:W5A", 5),
    );
    expect(await screen.findByTestId("hint-ward:W5A")).toHaveTextContent("ระบบ: 2");
    expect(tableInput("Stand By W5A")).toHaveValue(5);

    saveStandbyOverride.mockResolvedValueOnce(summary("night"));
    await user.click(within(screen.getByTestId("standby-table")).getByRole("button", { name: "คืนค่าระบบ Stand By W5A" }));
    await waitFor(() =>
      expect(saveStandbyOverride).toHaveBeenLastCalledWith(expect.any(String), "night", "ward:W5A", null),
    );
    await waitFor(() => expect(screen.queryByTestId("hint-ward:W5A")).toBeNull());
    expect(tableInput("Stand By W5A")).toHaveValue(2);
  });

  it("does not save an unchanged or invalid value", async () => {
    const user = userEvent.setup();
    setup();
    const input = await findTableInput("Stand By W5A");
    await user.click(input);
    await user.tab();
    await user.clear(input);
    await user.type(input, "-3");
    await user.tab();
    expect(saveStandbyOverride).not.toHaveBeenCalled();
    expect(input).toHaveValue(2);
  });

  it("previews the LINE text and copies it to the clipboard", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    setup();
    await waitFor(() => expect(screen.getByTestId("standby-text")).toHaveTextContent("W5A = 2 เครื่อง"));
    await user.click(screen.getByRole("button", { name: "คัดลอกข้อความ" }));
    expect(writeText).toHaveBeenCalledWith("Infusion pump standby\n28/07/2026\nW5A = 2 เครื่อง");
    expect(await screen.findByText("คัดลอกแล้ว")).toBeInTheDocument();
  });

  it("reports a clipboard failure", async () => {
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
      configurable: true,
    });
    setup();
    await waitFor(() => expect(screen.getByTestId("standby-text")).toHaveTextContent("W5A"));
    await user.click(screen.getByRole("button", { name: "คัดลอกข้อความ" }));
    expect(await screen.findByText(/คัดลอกไม่สำเร็จ/)).toBeInTheDocument();
  });

  it("saves the charger/clamp baseline from the dialog", async () => {
    const user = userEvent.setup();
    saveStandbyBaseline.mockResolvedValue({ chargers: 12, clamps: 9, set_at: "2026-07-28T00:00:00Z" });
    setup();
    await user.click(await screen.findByRole("button", { name: "ตั้งค่าเริ่มต้น สายชาร์จ/Clamp" }));
    const dialog = screen.getByRole("dialog");
    const chargers = within(dialog).getByLabelText("สายชาร์จที่คลัง");
    const clamps = within(dialog).getByLabelText("Clamp ที่คลัง");
    expect(chargers).toHaveValue(10);
    await user.clear(chargers);
    await user.type(chargers, "12");
    await user.clear(clamps);
    await user.type(clamps, "9");
    await user.click(within(dialog).getByRole("button", { name: "บันทึกค่าเริ่มต้น" }));
    await waitFor(() => expect(saveStandbyBaseline).toHaveBeenCalledWith(12, 9));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("downloads the PR30 daily Excel for the chosen date", async () => {
    const user = userEvent.setup();
    downloadDailySummary.mockResolvedValue(undefined);
    setup();
    await findTableInput("Stand By W5A");
    await user.click(screen.getByRole("button", { name: "ดาวน์โหลด Excel" }));
    expect(downloadDailySummary).toHaveBeenCalledWith(expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/), 60);
  });

  it("is not available to a read-only user and makes no request", () => {
    mockRole = "read_only";
    setup();
    expect(screen.getByText(/สำหรับเจ้าหน้าที่ศูนย์เครื่องมือ/)).toBeInTheDocument();
    expect(fetchStandbySummary).not.toHaveBeenCalled();
  });

  describe("mobile layout (CSS-only responsive)", () => {
    it("renders the md+ table and the <md grouped list with the right responsive classes", async () => {
      setup();
      const table = await screen.findByTestId("standby-table");
      expect(table.parentElement).toHaveClass("hidden", "md:block");
      expect(table).toHaveClass("table-fixed");
      const list = screen.getByTestId("standby-mobile-list");
      expect(list).toHaveClass("md:hidden");
      expect(within(list).queryByRole("table")).toBeNull();
    });

    it("shows one group header per mode/treatment with ward rows and 44px numeric inputs", async () => {
      setup();
      const list = await screen.findByTestId("standby-mobile-list");
      const groups = within(list).getAllByRole("group");
      expect(groups.length).toBeGreaterThan(0);
      for (const g of groups) expect(within(g).getAllByRole("heading", { level: 3 })).toHaveLength(1);
      const input = within(list).getByRole("spinbutton", { name: "Stand By W5A" });
      expect(input).toHaveAttribute("inputmode", "numeric");
      expect(input).toHaveClass("h-11", "w-[72px]");
      expect(within(list).getByText("W5B")).toBeInTheDocument();
    });

    it("marks an overridden ward as edited (แก้แล้ว) in the mobile list", async () => {
      fetchStandbySummary.mockImplementation((_d: string, c: StandbyCutoff) => Promise.resolve(summary(c, { "ward:W5A": 5 })));
      setup();
      const list = await screen.findByTestId("standby-mobile-list");
      expect(await within(list).findByTestId("m-edited-ward:W5A")).toHaveTextContent("แก้แล้ว");
      expect(within(list).getByTestId("m-hint-ward:W5A")).toHaveTextContent("ระบบ: 2");
    });
  });
});
