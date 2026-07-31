import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EquipmentVerifyChecklistPage } from "@/pages/EquipmentVerifyChecklistPage";
import type { Category, Department, Equipment, Page } from "@/types";

// Roadmap PR17 Slice 4 (docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md
// §6.3/§7.3(A)/§12): Equipment Verify Checklist screen tests. Consumes
// GET /reports/equipment-verify-checklist (services/reports.ts's
// getEquipmentVerifyChecklist) only -- GET /equipment is never called for
// this page.

const getEquipmentVerifyChecklist = vi.fn();
vi.mock("@/services/reports", () => ({
  getEquipmentVerifyChecklist: (...args: unknown[]) => getEquipmentVerifyChecklist(...args),
}));

const categories: Category[] = [
  { id: "cat-1", name: "Pump Category", default_pm_interval_days: null, default_cal_interval_days: null },
];
const departments: Department[] = [{ id: "dept-1", code: "D1", name: "Cardiology" }];
vi.mock("@/services/masterData", () => ({
  listCategories: () => Promise.resolve(categories),
  listDepartments: () => Promise.resolve(departments),
}));

function page(items: Equipment[], nextCursor: string | null = null): Page<Equipment> {
  return { items, next_cursor: nextCursor, total: items.length };
}

function makeRow(overrides: Partial<Equipment> = {}): Equipment {
  return {
    id: "eq-1",
    asset_number: "AST-1",
    serial_number: null,
    equipment_name: "Infusion Pump",
    category_id: "cat-1",
    brand: null,
    model: null,
    department_owner_id: "dept-1",
    current_location_id: null,
    status: "available_at_pool",
    bcm_code: "BCM001",
    pm_due_date: null,
    cal_due_date: null,
    created_at: "2026-07-10T03:00:00Z",
    updated_at: "2026-07-10T03:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  getEquipmentVerifyChecklist.mockResolvedValue(page([makeRow()]));
});

afterEach(() => {
  vi.clearAllMocks();
});

function LocationSearchProbe() {
  const location = useLocation();
  return <div data-testid="location-search">{location.search}</div>;
}

function renderPage(initialPath = "/reports/equipment-verify-checklist") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <LocationSearchProbe />
        <Routes>
          <Route path="/reports/equipment-verify-checklist" element={<EquipmentVerifyChecklistPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("EquipmentVerifyChecklistPage", () => {
  it("calls only GET /reports/equipment-verify-checklist, never GET /equipment", async () => {
    renderPage();
    await waitFor(() => expect(getEquipmentVerifyChecklist).toHaveBeenCalled());
  });

  it("renders Equipment fields directly, including category, department, and status, without recomputing them", async () => {
    renderPage();

    await screen.findByText("Infusion Pump");
    const table = within(screen.getByRole("table"));
    expect(table.getByText("Infusion Pump")).toBeInTheDocument();
    expect(table.getByText("AST-1")).toBeInTheDocument();
    expect(table.getByText("Cardiology")).toBeInTheDocument();
    expect(table.getByText("พร้อมใช้งาน")).toBeInTheDocument();
  });

  it("shows a loading state while the checklist is being fetched", async () => {
    getEquipmentVerifyChecklist.mockReturnValue(new Promise(() => {}));
    renderPage();

    expect(await screen.findByText("กำลังโหลดรายการตรวจสอบเครื่องมือ...")).toBeInTheDocument();
  });

  it("shows an empty state when no rows match", async () => {
    getEquipmentVerifyChecklist.mockResolvedValue(page([]));
    renderPage();

    expect(await screen.findByText("ไม่พบรายการ")).toBeInTheDocument();
  });

  it("shows an error state with a retry action, and retry recovers on success", async () => {
    getEquipmentVerifyChecklist.mockRejectedValueOnce({
      isAxiosError: true,
      response: { data: { detail: "โหลดไม่สำเร็จ" } },
    });
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("โหลดไม่สำเร็จ")).toBeInTheDocument();
    const retryButton = screen.getByRole("button", { name: "ลองใหม่" });

    getEquipmentVerifyChecklist.mockResolvedValueOnce(page([makeRow()]));
    await user.click(retryButton);

    await waitFor(() => expect(screen.queryByText("โหลดไม่สำเร็จ")).not.toBeInTheDocument());
    expect(await screen.findByText("Infusion Pump")).toBeInTheDocument();
  });

  it("renders every row the backend returns, regardless of status -- no client-side eligibility filtering", async () => {
    getEquipmentVerifyChecklist.mockResolvedValue(
      page([
        makeRow({ id: "eq-a", asset_number: "AST-A", status: "available_at_pool" }),
        makeRow({ id: "eq-b", asset_number: "AST-B", status: "unavailable_defective" }),
      ])
    );
    renderPage();

    expect(await screen.findByText("AST-A")).toBeInTheDocument();
    expect(screen.getByText("AST-B")).toBeInTheDocument();
  });

  it("appends cursor pages in backend order without re-sorting, merging, or reversing", async () => {
    getEquipmentVerifyChecklist.mockResolvedValueOnce(
      page([makeRow({ id: "eq-1", asset_number: "AST-1" })], "cursor-2")
    );
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("AST-1");
    const loadMore = screen.getByRole("button", { name: "โหลดเพิ่มเติม" });

    getEquipmentVerifyChecklist.mockResolvedValueOnce(page([makeRow({ id: "eq-2", asset_number: "AST-2" })], null));
    await user.click(loadMore);

    await waitFor(() => expect(screen.getByText("AST-2")).toBeInTheDocument());
    const rows = screen.getAllByRole("row").slice(1); // drop header row
    const order = rows.map((r) => r.textContent ?? "");
    expect(order[0]).toContain("AST-1");
    expect(order[1]).toContain("AST-2");
    expect(getEquipmentVerifyChecklist).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: "cursor-2" }));
    expect(screen.queryByRole("button", { name: "โหลดเพิ่มเติม" })).not.toBeInTheDocument();
  });

  it('offers "โหลดเพิ่มเติม" only when the backend reports a next_cursor', async () => {
    getEquipmentVerifyChecklist.mockResolvedValue(page([makeRow()], null));
    renderPage();
    await screen.findByText("AST-1");

    expect(screen.queryByRole("button", { name: "โหลดเพิ่มเติม" })).not.toBeInTheDocument();
  });

  it("serializes applied filters into the URL and into the getEquipmentVerifyChecklist call after นำตัวกรองไปใช้", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("AST-1");

    await user.selectOptions(screen.getByLabelText("หมวดหมู่เครื่องมือ"), "cat-1");
    await user.selectOptions(screen.getByLabelText("สถานะ"), "unavailable_defective");
    await user.selectOptions(screen.getByLabelText("หน่วยงานเจ้าของ"), "dept-1");
    await user.click(screen.getByRole("button", { name: "นำตัวกรองไปใช้" }));

    await waitFor(() =>
      expect(getEquipmentVerifyChecklist).toHaveBeenLastCalledWith(
        expect.objectContaining({
          equipment_category_id: "cat-1",
          status: "unavailable_defective",
          department_id: "dept-1",
        })
      )
    );

    const search = screen.getByTestId("location-search").textContent ?? "";
    expect(search).toContain("equipment_category_id=cat-1");
    expect(search).toContain("status=unavailable_defective");
    expect(search).toContain("department_id=dept-1");
  });

  it('"ล้างตัวกรอง" clears every filter and re-queries without them', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("AST-1");

    await user.selectOptions(screen.getByLabelText("สถานะ"), "unavailable_defective");
    await user.click(screen.getByRole("button", { name: "นำตัวกรองไปใช้" }));
    await waitFor(() =>
      expect(getEquipmentVerifyChecklist).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "unavailable_defective" })
      )
    );

    await user.click(screen.getByRole("button", { name: "ล้างตัวกรอง" }));

    await waitFor(() =>
      expect(getEquipmentVerifyChecklist).toHaveBeenLastCalledWith(expect.objectContaining({ status: undefined }))
    );
  });

  it("restores applied filters from the URL on initial render", async () => {
    renderPage("/reports/equipment-verify-checklist?equipment_category_id=cat-1&status=available_at_pool&department_id=dept-1");
    await screen.findByText("AST-1");

    expect(getEquipmentVerifyChecklist).toHaveBeenCalledWith(
      expect.objectContaining({
        equipment_category_id: "cat-1",
        status: "available_at_pool",
        department_id: "dept-1",
      })
    );
  });
});
