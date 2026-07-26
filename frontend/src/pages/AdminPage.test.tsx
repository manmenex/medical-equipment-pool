import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminPage } from "@/pages/AdminPage";
import type { ImportCommitResponse, ImportPreviewResponse, UserProfile } from "@/types";

// Roadmap PR12 (Inventory Import): this file exercises only the new
// "นำเข้าคลังเครื่องมือ" tab -- InventoryImportPanel. It does not exercise
// AdminPage's pre-existing tabs (EquipmentForm/DepartmentsList/etc.),
// which are unrelated to this PR's scope.

let mockUser: UserProfile | null = null;
vi.mock("@/hooks/useAuth", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useAuth")>("@/hooks/useAuth");
  return {
    ...actual,
    useAuth: () => ({ user: mockUser, isAuthenticated: true, isLoading: false }),
  };
});

const previewImport = vi.fn();
const commitImport = vi.fn();
vi.mock("@/services/import", () => ({
  previewImport: (...args: unknown[]) => previewImport(...args),
  commitImport: (...args: unknown[]) => commitImport(...args),
}));

function makeUser(role: UserProfile["role"]): UserProfile {
  return { id: "user-1", employee_code: "U001", full_name: "Test User", email: "u@test.dev", role, permissions: {} };
}

const previewResponse: ImportPreviewResponse = {
  filename: "inventory.xlsx",
  total_rows: 2,
  succeeded: 1,
  failed: 1,
  skipped: 0,
  rows: [
    {
      row_number: 2,
      bcm_code: "BCM001",
      item_no: null,
      asset_id: null,
      status: "success",
      action: "update",
      reason: null,
      equipment_id: null,
    },
    {
      row_number: 3,
      bcm_code: null,
      item_no: null,
      asset_id: null,
      status: "failed",
      action: null,
      reason: "Missing BCM Code (ID CODE column).",
      equipment_id: null,
    },
  ],
};

const commitResponse: ImportCommitResponse = {
  ...previewResponse,
  rows: [{ ...previewResponse.rows[0], equipment_id: "eq-1" }, previewResponse.rows[1]],
  audit_log_id: "audit-1",
};

function renderAdminPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AdminPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

async function openImportTab() {
  const user = userEvent.setup();
  renderAdminPage();
  await user.click(screen.getByRole("button", { name: "นำเข้าคลังเครื่องมือ" }));
  return user;
}

beforeEach(() => {
  mockUser = makeUser("administrator");
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("AdminPage import tab visibility", () => {
  it("shows the import tab to an administrator", () => {
    renderAdminPage();
    expect(screen.getByRole("button", { name: "นำเข้าคลังเครื่องมือ" })).toBeInTheDocument();
  });

  it("hides the import tab from a non-administrator", () => {
    mockUser = makeUser("equipment_pool_staff");
    renderAdminPage();
    expect(screen.queryByRole("button", { name: "นำเข้าคลังเครื่องมือ" })).not.toBeInTheDocument();
  });
});

describe("InventoryImportPanel upload -> preview -> commit", () => {
  it("uploads a file, previews it, and shows per-row results without committing", async () => {
    previewImport.mockResolvedValue(previewResponse);
    const user = await openImportTab();

    const file = new File(["dummy"], "inventory.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(fileInput, file);
    await user.click(screen.getByRole("button", { name: "ดูตัวอย่างก่อนนำเข้า" }));

    await waitFor(() => expect(previewImport).toHaveBeenCalledTimes(1));
    expect(previewImport).toHaveBeenCalledWith(file, false);
    expect(screen.getByText("ตัวอย่างผลการนำเข้า (ยังไม่บันทึกข้อมูลลงระบบ)")).toBeInTheDocument();
    expect(screen.getByText("สำเร็จ 1")).toBeInTheDocument();
    expect(screen.getByText("ล้มเหลว 1")).toBeInTheDocument();
    expect(screen.getByText("Missing BCM Code (ID CODE column).")).toBeInTheDocument();
    expect(commitImport).not.toHaveBeenCalled();
  });

  it("passes update_existing through to the preview call when the checkbox is checked", async () => {
    previewImport.mockResolvedValue(previewResponse);
    const user = await openImportTab();

    const file = new File(["dummy"], "inventory.xlsx", { type: "application/octet-stream" });
    await user.upload(document.querySelector('input[type="file"]') as HTMLInputElement, file);
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "ดูตัวอย่างก่อนนำเข้า" }));

    await waitFor(() => expect(previewImport).toHaveBeenCalledWith(file, true));
  });

  it("commits after a preview and shows the commit summary", async () => {
    previewImport.mockResolvedValue(previewResponse);
    commitImport.mockResolvedValue(commitResponse);
    const user = await openImportTab();

    const file = new File(["dummy"], "inventory.xlsx", { type: "application/octet-stream" });
    await user.upload(document.querySelector('input[type="file"]') as HTMLInputElement, file);
    await user.click(screen.getByRole("button", { name: "ดูตัวอย่างก่อนนำเข้า" }));
    await waitFor(() => expect(previewImport).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole("button", { name: "ยืนยันนำเข้า" }));
    await waitFor(() => expect(commitImport).toHaveBeenCalledTimes(1));
    expect(commitImport).toHaveBeenCalledWith(file, false);
    expect(screen.getByText("นำเข้าข้อมูลสำเร็จ")).toBeInTheDocument();
  });

  it("shows an error message and does not clear the preview when preview fails", async () => {
    previewImport.mockRejectedValue({
      isAxiosError: true,
      response: { data: { detail: "ไฟล์ไม่ถูกต้อง", code: "INVALID_INPUT", status: 400 } },
    });
    const user = await openImportTab();

    const file = new File(["dummy"], "bad.xlsx", { type: "application/octet-stream" });
    await user.upload(document.querySelector('input[type="file"]') as HTMLInputElement, file);
    await user.click(screen.getByRole("button", { name: "ดูตัวอย่างก่อนนำเข้า" }));

    await waitFor(() => expect(screen.getByText("ไฟล์ไม่ถูกต้อง")).toBeInTheDocument());
    expect(screen.queryByText("ตัวอย่างผลการนำเข้า (ยังไม่บันทึกข้อมูลลงระบบ)")).not.toBeInTheDocument();
  });

  it("disables the commit button when preview has zero succeeded rows", async () => {
    previewImport.mockResolvedValue({ ...previewResponse, succeeded: 0, failed: 2 });
    const user = await openImportTab();

    const file = new File(["dummy"], "inventory.xlsx", { type: "application/octet-stream" });
    await user.upload(document.querySelector('input[type="file"]') as HTMLInputElement, file);
    await user.click(screen.getByRole("button", { name: "ดูตัวอย่างก่อนนำเข้า" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "ยืนยันนำเข้า" })).toBeDisabled());
  });
});
