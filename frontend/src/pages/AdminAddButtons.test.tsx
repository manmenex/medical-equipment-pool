import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError } from "axios";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminPage } from "@/pages/AdminPage";
import type { UserProfile } from "@/types";

let mockUser: UserProfile | null = null;
vi.mock("@/hooks/useAuth", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useAuth")>("@/hooks/useAuth");
  return { ...actual, useAuth: () => ({ user: mockUser, isAuthenticated: true, isLoading: false }) };
});

const createDepartment = vi.fn();
const createWard = vi.fn();
const listDepartments = vi.fn();
const listWards = vi.fn();
vi.mock("@/services/masterData", () => ({
  listDepartments: () => listDepartments(),
  listWards: () => listWards(),
  listCategories: async () => [{ id: "c1", name: "เครื่องช่วยหายใจ", default_pm_interval_days: 90, default_cal_interval_days: 365 }],
  createDepartment: (...a: unknown[]) => createDepartment(...a),
  createWard: (...a: unknown[]) => createWard(...a),
  updateDepartmentPhone: vi.fn(),
  updateWardPhone: vi.fn(),
}));

function makeUser(role: UserProfile["role"]): UserProfile {
  return { id: "u1", employee_code: "U001", full_name: "T", email: "u@test.dev", role, permissions: {}, must_change_password: false };
}

function renderAt(url: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[url]}>
        <AdminPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function axiosErr(status: number) {
  const e = new AxiosError("x");
  e.response = { status, data: { detail: "dup" }, statusText: "", headers: {}, config: {} as never };
  return e;
}

beforeEach(() => {
  mockUser = makeUser("administrator");
  listDepartments.mockResolvedValue([{ id: "d1", code: "D1", name: "อายุรกรรม", phone: null }]);
  listWards.mockResolvedValue([]);
});
afterEach(() => vi.clearAllMocks());

describe("AdminPage ?tab= deep link", () => {
  it("opens the requested tab", async () => {
    renderAt("/admin?tab=departments");
    expect(await screen.findByRole("button", { name: "เพิ่มแผนก" })).toBeInTheDocument();
  });

  it("falls back to equipment for an unknown tab", () => {
    renderAt("/admin?tab=bogus");
    expect(screen.getByPlaceholderText("ชื่อเครื่องมือ")).toBeInTheDocument();
  });

  it("does not render a gated tab for a non-admin", () => {
    mockUser = makeUser("equipment_pool_staff");
    renderAt("/admin?tab=import");
    expect(screen.getByPlaceholderText("ชื่อเครื่องมือ")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "นำเข้าคลังเครื่องมือ" })).not.toBeInTheDocument();
  });

  it("opens demoLoan for an administrator", () => {
    renderAt("/admin?tab=demoLoan");
    expect(screen.queryByPlaceholderText("ชื่อเครื่องมือ")).not.toBeInTheDocument();
  });
});

describe("categories and locations tabs", () => {
  it("shows only the category name, without PM/CAL text", async () => {
    renderAt("/admin?tab=categories");
    expect(await screen.findByText("เครื่องช่วยหายใจ")).toBeInTheDocument();
    expect(screen.queryByText(/PM ทุก|CAL ทุก/)).not.toBeInTheDocument();
  });

  it("has no locations tab and ignores ?tab=locations", () => {
    renderAt("/admin?tab=locations");
    expect(screen.queryByRole("button", { name: "สถานที่" })).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("ชื่อเครื่องมือ")).toBeInTheDocument();
  });
});

describe("add department / ward", () => {
  it("creates a department and refreshes the list", async () => {
    createDepartment.mockResolvedValue({});
    renderAt("/admin?tab=departments");
    await userEvent.click(await screen.findByRole("button", { name: "เพิ่มแผนก" }));
    await userEvent.type(screen.getByLabelText("รหัสแผนก"), "D2");
    await userEvent.type(screen.getByLabelText("ชื่อแผนก"), "ศัลยกรรม");
    await userEvent.type(screen.getByLabelText("เบอร์โทร"), "1234");
    await userEvent.click(screen.getByRole("button", { name: "บันทึก" }));
    await waitFor(() => expect(createDepartment).toHaveBeenCalledWith({ code: "D2", name: "ศัลยกรรม", phone: "1234" }));
    await waitFor(() => expect(listDepartments.mock.calls.length).toBeGreaterThan(1));
  });

  it("shows a Thai duplicate error for a department", async () => {
    createDepartment.mockRejectedValue(axiosErr(409));
    renderAt("/admin?tab=departments");
    await userEvent.click(await screen.findByRole("button", { name: "เพิ่มแผนก" }));
    await userEvent.type(screen.getByLabelText("รหัสแผนก"), "D1");
    await userEvent.type(screen.getByLabelText("ชื่อแผนก"), "x");
    await userEvent.click(screen.getByRole("button", { name: "บันทึก" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("มีอยู่ในระบบแล้ว");
  });

  it("requires code and name", async () => {
    renderAt("/admin?tab=departments");
    await userEvent.click(await screen.findByRole("button", { name: "เพิ่มแผนก" }));
    await userEvent.click(screen.getByRole("button", { name: "บันทึก" }));
    expect(screen.getByRole("alert")).toHaveTextContent("กรุณากรอกรหัสและชื่อ");
    expect(createDepartment).not.toHaveBeenCalled();
  });

  it("creates a ward with its department", async () => {
    createWard.mockResolvedValue({});
    renderAt("/admin?tab=wards");
    await userEvent.click(await screen.findByRole("button", { name: "เพิ่มหอผู้ป่วย" }));
    await userEvent.type(screen.getByLabelText("รหัสหอผู้ป่วย"), "W1");
    await userEvent.type(screen.getByLabelText("ชื่อหอผู้ป่วย"), "หอ 1");
    await userEvent.selectOptions(await screen.findByLabelText("แผนก"), "d1");
    await userEvent.click(screen.getByRole("button", { name: "บันทึก" }));
    await waitFor(() =>
      expect(createWard).toHaveBeenCalledWith({ code: "W1", name: "หอ 1", phone: null, department_id: "d1" }),
    );
  });

  it("hides the add buttons from non-administrators", async () => {
    mockUser = makeUser("equipment_pool_staff");
    renderAt("/admin?tab=wards");
    await waitFor(() => expect(listWards).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "เพิ่มหอผู้ป่วย" })).not.toBeInTheDocument();
  });
});
