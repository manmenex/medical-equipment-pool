import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SyncReviewPage } from "@/pages/SyncReviewPage";
import type { SyncConflictItem } from "@/services/syncReview";
import type { UserProfile } from "@/types";

const fetchSyncConflicts = vi.fn();
const dismissSyncConflict = vi.fn();
const applySyncConflictNow = vi.fn();
vi.mock("@/services/syncReview", () => ({
  fetchSyncConflicts: (...a: unknown[]) => fetchSyncConflicts(...a),
  dismissSyncConflict: (...a: unknown[]) => dismissSyncConflict(...a),
  applySyncConflictNow: (...a: unknown[]) => applySyncConflictNow(...a),
}));

let mockUser: UserProfile | null = null;
vi.mock("@/hooks/useAuth", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useAuth")>("@/hooks/useAuth");
  return { ...actual, useAuth: () => ({ user: mockUser, isAuthenticated: true, isLoading: false }) };
});

function makeUser(role: UserProfile["role"]): UserProfile {
  return { id: "u1", employee_code: "U001", full_name: "Test", email: "u@test.dev", role, permissions: {}, must_change_password: false };
}

function item(over: Partial<SyncConflictItem> = {}): SyncConflictItem {
  return {
    op_id: "op-1",
    op_type: "dispatch",
    status: "conflict",
    result_code: "OP_TOO_OLD",
    admin_only: false,
    stale_context: false,
    device_id: "dev-A",
    received_at: "2026-10-01T00:00:00Z",
    first_seen_at: "2026-10-01T00:00:00Z",
    occurred_at: "2026-09-28T00:00:00Z",
    attempt_count: 1,
    operator: { id: "o1", full_name: "สมชาย ใจดี" },
    equipment: { id: "e1", bcm_code: "BCM123", equipment_name: "Pump", status: "available" },
    ward_name: "ICU",
    transaction_id: null,
    receipt_outcome: null,
    resolution: null,
    dismiss_reason: null,
    ...over,
  };
}

function apiError(status: number, code: string) {
  return { isAxiosError: true, response: { status, data: { code, detail: "x" } } };
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SyncReviewPage />
    </QueryClientProvider>,
  );
}

const page = (items: SyncConflictItem[]) => ({ total: items.length, limit: 100, offset: 0, items });

beforeEach(() => {
  mockUser = makeUser("equipment_pool_staff");
  fetchSyncConflicts.mockReset().mockResolvedValue(page([item()]));
  dismissSyncConflict.mockReset().mockResolvedValue(undefined);
  applySyncConflictNow.mockReset().mockResolvedValue(undefined);
});
afterEach(() => vi.clearAllMocks());

describe("SyncReviewPage", () => {
  it("renders list rows with OP_TOO_OLD explanation", async () => {
    renderPage();
    expect(await screen.findByText("BCM123")).toBeInTheDocument();
    expect(screen.getByText("OP_TOO_OLD")).toBeInTheDocument();
    expect(screen.getByText(/เกิน 7 วัน/)).toBeInTheDocument();
    expect(screen.getByText("ICU")).toBeInTheDocument();
    expect(screen.getByText("สมชาย ใจดี")).toBeInTheDocument();
    expect(screen.getByText("dev-A")).toBeInTheDocument();
  });

  it("dismisses with a required reason after confirmation", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "ปิดรายการ" }));
    const confirm = screen.getByRole("button", { name: "ยืนยัน" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText("เหตุผล"), { target: { value: "not_real" } });
    fireEvent.click(confirm);
    await waitFor(() => expect(dismissSyncConflict).toHaveBeenCalledWith("op-1", "not_real", undefined));
    await waitFor(() => expect(fetchSyncConflicts.mock.calls.length).toBeGreaterThan(1));
  });

  it("applies now after confirmation and disables while in flight", async () => {
    let release: () => void = () => undefined;
    applySyncConflictNow.mockReturnValue(new Promise<void>((r) => (release = r)));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "บันทึกทันที" }));
    expect(applySyncConflictNow).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "ยืนยัน" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "กำลังดำเนินการ..." })).toBeDisabled());
    expect(applySyncConflictNow).toHaveBeenCalledWith("op-1");
    release();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("handles 409 SYNC_OP_NOT_RESOLVABLE by refreshing", async () => {
    applySyncConflictNow.mockRejectedValue(apiError(409, "SYNC_OP_NOT_RESOLVABLE"));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "บันทึกทันที" }));
    fireEvent.click(screen.getByRole("button", { name: "ยืนยัน" }));
    expect(await screen.findByText(/ถูกดำเนินการไปแล้ว/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(fetchSyncConflicts.mock.calls.length).toBeGreaterThan(1));
  });

  it("shows SYNC_APPLY_FAILED in the dialog and refreshes", async () => {
    applySyncConflictNow.mockRejectedValue(apiError(409, "SYNC_APPLY_FAILED"));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "บันทึกทันที" }));
    fireEvent.click(screen.getByRole("button", { name: "ยืนยัน" }));
    const box = await screen.findByText(/เงื่อนไขของอุปกรณ์เปลี่ยนไปแล้ว/);
    expect(box).toHaveClass("text-status-repair");
    expect(box).not.toHaveClass("bg-status-available/15");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(fetchSyncConflicts.mock.calls.length).toBeGreaterThan(1));
  });

  it("states which time apply-now will record", async () => {
    fetchSyncConflicts.mockResolvedValue(
      page([item(), item({ op_id: "op-2", result_code: "EQUIPMENT_NOT_AVAILABLE" })]),
    );
    renderPage();
    const buttons = await screen.findAllByRole("button", { name: "บันทึกทันที" });
    fireEvent.click(buttons[0]);
    expect(screen.getByRole("dialog")).toHaveTextContent(new Date("2026-09-28T00:00:00Z").toLocaleString("th-TH"));
    fireEvent.click(screen.getByRole("button", { name: "ยกเลิก" }));
    fireEvent.click(buttons[1]);
    expect(screen.getByRole("dialog")).toHaveTextContent("เวลาปัจจุบัน");
  });

  it("shows a truncation note when total exceeds shown items", async () => {
    fetchSyncConflicts.mockResolvedValue({ total: 250, limit: 100, offset: 0, items: [item()] });
    renderPage();
    expect(await screen.findByText("แสดง 1 จาก 250 รายการ")).toBeInTheDocument();
  });

  it("denies read-only users without calling the API", () => {
    mockUser = makeUser("read_only");
    renderPage();
    expect(screen.getByText("คุณไม่มีสิทธิ์เข้าถึงหน้านี้")).toBeInTheDocument();
    expect(fetchSyncConflicts).not.toHaveBeenCalled();
  });

  it("disables actions on admin-only rows for staff", async () => {
    fetchSyncConflicts.mockResolvedValue(page([item({ admin_only: true, result_code: "FORBIDDEN" })]));
    renderPage();
    expect(await screen.findByRole("button", { name: "ปิดรายการ" })).toBeDisabled();
  });
});
