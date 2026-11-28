import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OtherUsersOutboxPanel } from "@/components/OtherUsersOutboxPanel";
import type { UserProfile } from "@/types";

const listAdoptableGroups = vi.fn();
const adoptOps = vi.fn();
const reauthenticate = vi.fn();
vi.mock("@/offline/adoption", () => ({
  listAdoptableGroups: (...a: unknown[]) => listAdoptableGroups(...a),
  adoptOps: (...a: unknown[]) => adoptOps(...a),
  reauthenticate: (...a: unknown[]) => reauthenticate(...a),
}));

let mockUser: UserProfile | null = null;
vi.mock("@/hooks/useAuth", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useAuth")>("@/hooks/useAuth");
  return { ...actual, useAuth: () => ({ user: mockUser, isAuthenticated: true, isLoading: false }) };
});
let mockOffline = false;
vi.mock("@/hooks/useOfflineMode", () => ({ useOfflineMode: () => mockOffline }));

const user = (role: UserProfile["role"]): UserProfile =>
  ({ id: "u1", employee_code: "U001", full_name: "Me", email: "", role, permissions: {}, must_change_password: false }) as UserProfile;

const group = {
  user_id: "orig",
  name: "สมชาย",
  count: 2,
  ops: [{ op_id: "o1", original_user_id: "orig", op_type: "dispatch", bcm_code: "BCM1", occurred_at: "2026-10-13T08:00:00Z" }],
};
const summary = { applied: 2, duplicate: 0, conflict: 0, rejected: 0, left_pending: 0, reauth_required: false, error: null };

function renderPanel() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <OtherUsersOutboxPanel />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockOffline = false;
  mockUser = user("equipment_pool_staff");
  listAdoptableGroups.mockResolvedValue([group]);
  adoptOps.mockResolvedValue(summary);
  reauthenticate.mockResolvedValue(undefined);
});

describe("OtherUsersOutboxPanel", () => {
  it("shows per-user count for pool staff", async () => {
    renderPanel();
    expect(await screen.findByText(/สมชาย — 2 รายการ/)).toBeInTheDocument();
  });

  it("renders nothing for read-only users and never reads the outbox", async () => {
    mockUser = user("read_only");
    renderPanel();
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText("รายการค้างของผู้ใช้อื่น")).toBeNull();
    expect(listAdoptableGroups).not.toHaveBeenCalled();
  });

  it("renders nothing when no other user's items exist", async () => {
    listAdoptableGroups.mockResolvedValue([]);
    renderPanel();
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText("รายการค้างของผู้ใช้อื่น")).toBeNull();
  });

  it("requires the password, re-logs in, then sends and shows the result", async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "ส่งแทน" }));
    const confirmBtn = screen.getByRole("button", { name: "ยืนยันและส่ง" });
    expect(confirmBtn).toBeDisabled(); // no password yet
    fireEvent.change(screen.getByLabelText(/ยืนยันรหัสผ่าน/), { target: { value: "pw" } });
    fireEvent.click(confirmBtn);
    await waitFor(() => expect(adoptOps).toHaveBeenCalled());
    expect(reauthenticate).toHaveBeenCalledWith("pw");
    expect(adoptOps.mock.calls[0][1]).toEqual(new Set(["orig"]));
    expect(await screen.findByTestId("adopt-summary")).toHaveTextContent("ส่งสำเร็จ 2 รายการ");
  });

  it("wrong password: nothing is sent", async () => {
    reauthenticate.mockRejectedValue(new Error("bad"));
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "ส่งแทน" }));
    fireEvent.change(screen.getByLabelText(/ยืนยันรหัสผ่าน/), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "ยืนยันและส่ง" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(adoptOps).not.toHaveBeenCalled();
  });

  it("conflicts are reported with a pointer to the review list", async () => {
    adoptOps.mockResolvedValue({ ...summary, applied: 0, conflict: 2 });
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "ส่งแทน" }));
    fireEvent.change(screen.getByLabelText(/ยืนยันรหัสผ่าน/), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: "ยืนยันและส่ง" }));
    expect(await screen.findByTestId("adopt-summary")).toHaveTextContent("ต้องตรวจสอบ 2 รายการ");
  });

  it("button is disabled while offline", async () => {
    mockOffline = true;
    renderPanel();
    expect(await screen.findByRole("button", { name: "ส่งแทน" })).toBeDisabled();
  });
});
