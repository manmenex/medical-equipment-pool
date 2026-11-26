import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsPage } from "@/pages/SettingsPage";
import type { UserProfile } from "@/types";

const fetchSyncConflicts = vi.fn();
vi.mock("@/services/syncReview", () => ({ fetchSyncConflicts: (...a: unknown[]) => fetchSyncConflicts(...a) }));

let mockUser: UserProfile | null = null;
vi.mock("@/hooks/useAuth", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useAuth")>("@/hooks/useAuth");
  return { ...actual, useAuth: () => ({ user: mockUser, isAuthenticated: true, isLoading: false }) };
});

function makeUser(role: UserProfile["role"]): UserProfile {
  return { id: "u1", employee_code: "U001", full_name: "Test User", email: "u@test.dev", role, permissions: {}, must_change_password: false };
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SettingsPage hub", () => {
  beforeEach(() => {
    fetchSyncConflicts.mockReset().mockResolvedValue({ total: 4, limit: 1, offset: 0, items: [] });
  });

  it("keeps personal settings", () => {
    mockUser = makeUser("read_only");
    renderPage();
    expect(screen.getByRole("link", { name: "เปลี่ยนรหัสผ่าน" })).toHaveAttribute("href", "/change-password");
    expect(screen.getByRole("button", { name: "มืด" })).toBeInTheDocument();
  });

  it("shows every card with descriptions and the review count for an administrator", async () => {
    mockUser = makeUser("administrator");
    renderPage();
    expect(screen.getByText("การจัดการข้อมูล")).toBeInTheDocument();
    expect(screen.getByText("การย้ายระบบ")).toBeInTheDocument();
    const hrefs: Record<string, string> = {
      "จัดการระบบ": "/admin",
      "นำเข้าข้อมูลเดิม": "/imports",
      "ตรวจสอบรายการออฟไลน์": "/sync-review",
      "ตรวจสอบข้อมูลย้อนหลัง": "/reconciliation",
      "ความพร้อมก่อนเปลี่ยนระบบ": "/cutover-readiness",
    };
    for (const [name, href] of Object.entries(hrefs)) {
      expect(screen.getByRole("link", { name: new RegExp(name) })).toHaveAttribute("href", href);
    }
    expect(screen.getByText("เทียบข้อมูลระบบเดิมกับระบบนี้")).toBeInTheDocument();
    expect(screen.getByText("เช็กลิสต์ก่อนเลิกใช้ระบบเดิม")).toBeInTheDocument();
    expect(await screen.findByLabelText("รอตรวจสอบ 4 รายการ")).toBeInTheDocument();
  });

  it("hides admin-only cards for equipment pool staff", () => {
    mockUser = makeUser("equipment_pool_staff");
    renderPage();
    expect(screen.queryByRole("link", { name: /จัดการระบบ/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /นำเข้าข้อมูลเดิม/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /ตรวจสอบรายการออฟไลน์/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /ตรวจสอบข้อมูลย้อนหลัง/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /ความพร้อมก่อนเปลี่ยนระบบ/ })).toBeInTheDocument();
  });

  it("shows no offline review card and makes no request for read-only users", () => {
    mockUser = makeUser("read_only");
    renderPage();
    expect(screen.queryByRole("link", { name: /ตรวจสอบรายการออฟไลน์/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /จัดการระบบ/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /ตรวจสอบข้อมูลย้อนหลัง/ })).toBeInTheDocument();
    expect(fetchSyncConflicts).not.toHaveBeenCalled();
  });
});
