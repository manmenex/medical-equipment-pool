import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
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

vi.mock("@/services/masterData", () => ({
  listWards: () => Promise.resolve([]),
  listDepartments: () => Promise.resolve([]),
  listLocations: () => Promise.resolve([]),
  listCategories: () => Promise.resolve([]),
  updateWardPhone: vi.fn(),
  updateDepartmentPhone: vi.fn(),
  importWardPhones: vi.fn(),
}));

const listUsers = vi.fn();
const createUser = vi.fn();
const updateUser = vi.fn();
const resetUserPassword = vi.fn();
vi.mock("@/services/users", () => ({
  listUsers: (...a: unknown[]) => listUsers(...a),
  createUser: (...a: unknown[]) => createUser(...a),
  updateUser: (...a: unknown[]) => updateUser(...a),
  resetUserPassword: (...a: unknown[]) => resetUserPassword(...a),
}));

function makeUser(role: UserProfile["role"]): UserProfile {
  return { id: "me", employee_code: "ME", full_name: "Me", email: "me@t.dev", role, permissions: {}, must_change_password: false };
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

const ROWS = [
  { id: "me", employee_code: "ME", full_name: "Me", email: "me@t.dev", role: "administrator", is_active: true },
  { id: "u1", employee_code: "E100", full_name: "Somchai", email: "s@t.dev", role: "read_only", is_active: true },
];

beforeEach(() => {
  vi.resetAllMocks();
  listUsers.mockResolvedValue(ROWS);
});

async function openUsersTab() {
  const user = userEvent.setup();
  renderAdmin();
  await user.click(screen.getByRole("button", { name: "ผู้ใช้" }));
  await screen.findByText("E100");
  return user;
}

describe("Admin users tab", () => {
  it("is hidden from non-administrators", () => {
    mockUser = makeUser("equipment_pool_staff");
    renderAdmin();
    expect(screen.queryByRole("button", { name: "ผู้ใช้" })).not.toBeInTheDocument();
  });

  it("lists users with Thai role labels", async () => {
    mockUser = makeUser("administrator");
    await openUsersTab();
    expect(screen.getByText("Somchai")).toBeInTheDocument();
    expect(screen.getByLabelText("ระดับสิทธิ์ E100")).toHaveValue("read_only");
    expect(screen.getAllByText("ใช้งาน").length).toBeGreaterThan(0);
  });

  it("creates a user with initial password and role", async () => {
    mockUser = makeUser("administrator");
    createUser.mockResolvedValue({ ...ROWS[1], employee_code: "E200" });
    const user = await openUsersTab();
    await user.type(screen.getByPlaceholderText("รหัสพนักงาน"), "E200");
    await user.type(screen.getByPlaceholderText("ชื่อ-นามสกุล"), "New Person");
    await user.type(screen.getByPlaceholderText("อีเมล"), "n@t.dev");
    await user.type(screen.getByPlaceholderText("รหัสผ่านเริ่มต้น"), "Initial-Pw-1");
    await user.selectOptions(screen.getByLabelText("ระดับสิทธิ์ผู้ใช้ใหม่"), "equipment_pool_staff");
    await user.click(screen.getByRole("button", { name: "เพิ่มผู้ใช้" }));
    await waitFor(() =>
      expect(createUser).toHaveBeenCalledWith({
        employee_code: "E200",
        full_name: "New Person",
        email: "n@t.dev",
        password: "Initial-Pw-1",
        role_name: "equipment_pool_staff",
      }),
    );
  });

  it("changes role and toggles active", async () => {
    mockUser = makeUser("administrator");
    updateUser.mockResolvedValue(ROWS[1]);
    const user = await openUsersTab();
    await user.selectOptions(screen.getByLabelText("ระดับสิทธิ์ E100"), "equipment_pool_staff");
    await waitFor(() => expect(updateUser).toHaveBeenCalledWith("u1", { role_name: "equipment_pool_staff" }));
    await user.click(screen.getByRole("button", { name: "ปิดใช้งาน E100" }));
    await waitFor(() => expect(updateUser).toHaveBeenCalledWith("u1", { is_active: false }));
  });

  it("does not offer self-modification", async () => {
    mockUser = makeUser("administrator");
    await openUsersTab();
    expect(screen.getByRole("button", { name: "รีเซ็ตรหัสผ่าน ME" })).toBeDisabled();
  });

  it("resets a password after confirm and shows the temp password once", async () => {
    mockUser = makeUser("administrator");
    resetUserPassword.mockResolvedValue({ employee_code: "E100", temporary_password: "Temp-Secret-XYZ" });
    const user = await openUsersTab();
    // userEvent.setup() installs its own clipboard stub; spy on it afterwards.
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined);

    await user.click(screen.getByRole("button", { name: "รีเซ็ตรหัสผ่าน E100" }));
    expect(resetUserPassword).not.toHaveBeenCalled();
    const confirm = screen.getByRole("dialog", { name: "ยืนยันการรีเซ็ตรหัสผ่าน" });
    await user.click(within(confirm).getByRole("button", { name: "ยืนยัน" }));

    const dialog = await screen.findByRole("dialog", { name: "รหัสผ่านชั่วคราว" });
    expect(resetUserPassword).toHaveBeenCalledWith("u1");
    expect(within(dialog).getByTestId("temp-password")).toHaveTextContent("Temp-Secret-XYZ");
    expect(within(dialog).getByRole("note")).toHaveTextContent("เพียงครั้งเดียว");

    await user.click(within(dialog).getByRole("button", { name: "คัดลอก" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("Temp-Secret-XYZ"));

    await user.click(within(dialog).getByRole("button", { name: "ปิด" }));
    expect(screen.queryByText("Temp-Secret-XYZ")).not.toBeInTheDocument();
  });

  it("cancelling the confirm does not reset", async () => {
    mockUser = makeUser("administrator");
    const user = await openUsersTab();
    await user.click(screen.getByRole("button", { name: "รีเซ็ตรหัสผ่าน E100" }));
    await user.click(screen.getByRole("button", { name: "ยกเลิก" }));
    expect(resetUserPassword).not.toHaveBeenCalled();
  });
});
