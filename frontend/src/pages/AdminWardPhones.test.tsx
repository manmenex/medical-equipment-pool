import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminPage } from "@/pages/AdminPage";
import type { UserProfile } from "@/types";

let mockUser: UserProfile | null = null;
vi.mock("@/hooks/useAuth", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useAuth")>("@/hooks/useAuth");
  return { ...actual, useAuth: () => ({ user: mockUser, isAuthenticated: true, isLoading: false }) };
});

const updateWardPhone = vi.fn();
const importWardPhones = vi.fn();
vi.mock("@/services/masterData", () => ({
  listWards: () => Promise.resolve([{ id: "w1", code: "W1", name: "Ward A", department_id: null, phone: "111" }]),
  listDepartments: () => Promise.resolve([{ id: "d1", code: "D1", name: "Dep", phone: null }]),
  listLocations: () => Promise.resolve([]),
  listCategories: () => Promise.resolve([]),
  updateWardPhone: (...a: unknown[]) => updateWardPhone(...a),
  updateDepartmentPhone: vi.fn(),
  importWardPhones: (...a: unknown[]) => importWardPhones(...a),
}));

function makeUser(role: UserProfile["role"]): UserProfile {
  return { id: "u", employee_code: "U1", full_name: "T", email: "t@t.dev", role, permissions: {}, must_change_password: false };
}
function renderAdmin() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AdminPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Admin ward/department phone UI (Roadmap PR25E S0)", () => {
  it("hides edit controls and the import tab from non-administrators", async () => {
    mockUser = makeUser("equipment_pool_staff");
    const user = userEvent.setup();
    renderAdmin();
    expect(screen.queryByRole("button", { name: "นำเข้าเบอร์โทรหอผู้ป่วย" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "หอผู้ป่วย" }));
    await waitFor(() => expect(screen.getByText(/เบอร์โทร: 111/)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "แก้ไขเบอร์โทร" })).not.toBeInTheDocument();
  });

  it("lets an administrator PATCH a ward phone", async () => {
    mockUser = makeUser("administrator");
    updateWardPhone.mockResolvedValue({});
    const user = userEvent.setup();
    renderAdmin();
    await user.click(screen.getByRole("button", { name: "หอผู้ป่วย" }));
    await user.click(await screen.findByRole("button", { name: "แก้ไขเบอร์โทร" }));
    const input = screen.getByLabelText("เบอร์โทร");
    await user.clear(input);
    await user.type(input, "2222");
    await user.click(screen.getByRole("button", { name: "บันทึก" }));
    await waitFor(() => expect(updateWardPhone).toHaveBeenCalledWith("w1", "2222"));
  });

  it("runs dry-run then explicit confirm for the bulk import", async () => {
    mockUser = makeUser("administrator");
    const results = [
      { ward_name: "Ward A", phone: "1", status: "will_set" },
      { ward_name: "Nope", phone: "2", status: "unknown_ward" },
    ];
    importWardPhones
      .mockResolvedValueOnce({ applied: false, counts: { will_set: 1, unknown_ward: 1 }, results })
      .mockResolvedValueOnce({ applied: true, counts: { will_set: 1, unknown_ward: 1 }, results });
    const user = userEvent.setup();
    renderAdmin();
    await user.click(screen.getByRole("button", { name: "นำเข้าเบอร์โทรหอผู้ป่วย" }));
    await user.click(screen.getByLabelText("ข้อมูล CSV"));
    await user.paste("﻿ward_name,nsmart_department,phone\nWard A,x,1\nNope,y,2");
    await user.click(screen.getByLabelText("เขียนทับเบอร์โทรที่มีอยู่แล้ว"));
    await user.click(screen.getByRole("button", { name: /Dry-run/ }));

    expect(await screen.findByText("จะตั้งเบอร์ใหม่")).toBeInTheDocument();
    expect(screen.getByText("ไม่พบหอผู้ป่วย")).toBeInTheDocument();
    expect(importWardPhones).toHaveBeenCalledWith(
      [{ ward_name: "Ward A", phone: "1" }, { ward_name: "Nope", phone: "2" }],
      { dryRun: true, overwrite: true },
    );
    expect(importWardPhones).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: /ยืนยันนำเข้า/ }));
    await waitFor(() => expect(importWardPhones).toHaveBeenCalledTimes(2));
    expect(importWardPhones.mock.calls[1][1]).toEqual({ dryRun: false, overwrite: true });
    expect(await screen.findByText("นำเข้าเบอร์โทรสำเร็จ")).toBeInTheDocument();
  });
});
