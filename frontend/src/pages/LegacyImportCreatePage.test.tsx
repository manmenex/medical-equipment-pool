import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LegacyImportCreatePage } from "@/pages/LegacyImportCreatePage";
import { api } from "@/services/api";
import type { UserProfile } from "@/types";

const createEquipmentMasterSession = vi.fn();
const uploadEquipmentMasterSource = vi.fn();
vi.mock("@/services/equipmentMasterImportClient", () => ({
  createEquipmentMasterSession: (...args: unknown[]) => createEquipmentMasterSession(...args),
  uploadEquipmentMasterSource: (...args: unknown[]) => uploadEquipmentMasterSource(...args),
}));

const createLegacyHistorySession = vi.fn();
const uploadLegacyHistorySource = vi.fn();
vi.mock("@/services/legacyHistoryImportClient", () => ({
  createLegacyHistorySession: (...args: unknown[]) => createLegacyHistorySession(...args),
  uploadLegacyHistorySource: (...args: unknown[]) => uploadLegacyHistorySource(...args),
}));

const approveLegacyMigrationAuthority = vi.fn();
const findLegacyMigrationAuthorityByChecksum = vi.fn();
vi.mock("@/services/legacyMigrationAuthorityClient", () => ({
  approveLegacyMigrationAuthority: (...args: unknown[]) => approveLegacyMigrationAuthority(...args),
  findLegacyMigrationAuthorityByChecksum: (...args: unknown[]) => findLegacyMigrationAuthorityByChecksum(...args),
}));

let mockUser: UserProfile | null = null;
vi.mock("@/hooks/useAuth", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useAuth")>("@/hooks/useAuth");
  return {
    ...actual,
    useAuth: () => ({ user: mockUser, isAuthenticated: true, isLoading: false }),
  };
});

function makeUser(role: UserProfile["role"]): UserProfile {
  return { id: "user-1", employee_code: "U001", full_name: "Test User", email: "u@test.dev", role, permissions: {} };
}

beforeEach(() => {
  mockUser = makeUser("administrator");
  vi.spyOn(api, "post");
  vi.spyOn(api, "get");
});

afterEach(() => {
  vi.resetAllMocks();
});

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/imports/new"]}>
        <Routes>
          <Route path="/imports/new" element={<LegacyImportCreatePage />} />
          <Route path="/imports/:sessionId" element={<div>session detail page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function makeTestFile(name = "legacy-history.xlsx", sizeBytes = 2048): File {
  return new File([new Uint8Array(sizeBytes)], name, {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

describe("LegacyImportCreatePage", () => {
  it("requires an import type before continuing to the file step", async () => {
    const user = userEvent.setup();
    renderPage();

    const next = screen.getByRole("button", { name: "ถัดไป" });
    expect(next).toBeDisabled();

    await user.click(screen.getByLabelText(/ประวัติการรับ-ส่งเครื่องมือเดิม/));
    expect(next).toBeEnabled();

    await user.click(next);
    expect(await screen.findByLabelText("เลือกไฟล์สำหรับนำเข้าข้อมูลเดิม")).toBeInTheDocument();
  });

  it("keeps ตรวจสอบข้อมูล disabled until a file is selected, then shows the selected file summary", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByLabelText(/ข้อมูลหลักเครื่องมือ/));
    await user.click(screen.getByRole("button", { name: "ถัดไป" }));

    const continueButton = screen.getByRole("button", { name: "ตรวจสอบข้อมูล" });
    expect(continueButton).toBeDisabled();

    const input = screen.getByLabelText("เลือกไฟล์สำหรับนำเข้าข้อมูลเดิม");
    await user.upload(input, makeTestFile("equipment.xlsx"));

    expect(await screen.findByText("equipment.xlsx")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ตรวจสอบข้อมูล" })).toBeEnabled();
  });

  it("replace/remove clears the selected file and disables continue again", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByLabelText(/ข้อมูลหลักเครื่องมือ/));
    await user.click(screen.getByRole("button", { name: "ถัดไป" }));
    await user.upload(screen.getByLabelText("เลือกไฟล์สำหรับนำเข้าข้อมูลเดิม"), makeTestFile("equipment.xlsx"));
    await screen.findByText("equipment.xlsx");

    await user.click(screen.getByRole("button", { name: "เปลี่ยนไฟล์" }));

    expect(screen.queryByText("equipment.xlsx")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ตรวจสอบข้อมูล" })).toBeDisabled();
  });

  it("continuing for equipment_master creates a real session, uploads the file through the real API, and navigates to the created session", async () => {
    createEquipmentMasterSession.mockResolvedValue({ id: "11111111-1111-4111-8111-111111111111" });
    uploadEquipmentMasterSource.mockResolvedValue({ id: "source-1" });
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByLabelText(/ข้อมูลหลักเครื่องมือ/));
    await user.click(screen.getByRole("button", { name: "ถัดไป" }));
    await user.upload(screen.getByLabelText("เลือกไฟล์สำหรับนำเข้าข้อมูลเดิม"), makeTestFile("equipment.xlsx", 4096));
    await screen.findByText("equipment.xlsx");

    await user.click(screen.getByRole("button", { name: "ตรวจสอบข้อมูล" }));

    await waitFor(() => expect(uploadEquipmentMasterSource).toHaveBeenCalledTimes(1));
    expect(createEquipmentMasterSession).toHaveBeenCalledTimes(1);
    const [sessionIdArg, fileArg] = uploadEquipmentMasterSource.mock.calls[0] as [string, File];
    expect(sessionIdArg).toBe("11111111-1111-4111-8111-111111111111");
    expect(fileArg.name).toBe("equipment.xlsx");
    expect(createLegacyHistorySession).not.toHaveBeenCalled();

    expect(await screen.findByText("session detail page")).toBeInTheDocument();
  });

  it("retries an equipment_master upload against the same session instead of creating a second one", async () => {
    createEquipmentMasterSession.mockResolvedValue({ id: "22222222-2222-4222-8222-222222222222" });
    uploadEquipmentMasterSource.mockRejectedValueOnce(new Error("network error"));
    uploadEquipmentMasterSource.mockResolvedValueOnce({ id: "source-1" });
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByLabelText(/ข้อมูลหลักเครื่องมือ/));
    await user.click(screen.getByRole("button", { name: "ถัดไป" }));
    await user.upload(screen.getByLabelText("เลือกไฟล์สำหรับนำเข้าข้อมูลเดิม"), makeTestFile("equipment.xlsx"));
    await screen.findByText("equipment.xlsx");

    await user.click(screen.getByRole("button", { name: "ตรวจสอบข้อมูล" }));
    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: "ตรวจสอบข้อมูล" }));

    await waitFor(() => expect(uploadEquipmentMasterSource).toHaveBeenCalledTimes(2));
    expect(createEquipmentMasterSession).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("session detail page")).toBeInTheDocument();
  });

  it("shows a back-navigation control between steps", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByLabelText(/ข้อมูลหลักเครื่องมือ/));
    await user.click(screen.getByRole("button", { name: "ถัดไป" }));
    expect(screen.getByLabelText("เลือกไฟล์สำหรับนำเข้าข้อมูลเดิม")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "ย้อนกลับ" }));
    expect(screen.getByRole("button", { name: "ถัดไป" })).toBeInTheDocument();
  });

  // Bug-fix regression: switching import category after a file was already
  // selected must not silently carry that file over to the new category --
  // it must clear the file, any file-related error, and re-disable
  // ตรวจสอบข้อมูล until a new valid file is chosen for the new category.
  it("clears the selected file, its error state, and re-disables continue when the category changes", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByLabelText(/ข้อมูลหลักเครื่องมือ/));
    await user.click(screen.getByRole("button", { name: "ถัดไป" }));
    await user.upload(screen.getByLabelText("เลือกไฟล์สำหรับนำเข้าข้อมูลเดิม"), makeTestFile("equipment.xlsx"));
    await screen.findByText("equipment.xlsx");
    expect(screen.getByRole("button", { name: "ตรวจสอบข้อมูล" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "ย้อนกลับ" }));
    await user.click(screen.getByLabelText(/ประวัติการรับ-ส่งเครื่องมือเดิม/));
    await user.click(screen.getByRole("button", { name: "ถัดไป" }));

    expect(screen.queryByText("equipment.xlsx")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ตรวจสอบข้อมูล" })).toBeDisabled();
    expect(screen.getByLabelText("เลือกไฟล์สำหรับนำเข้าข้อมูลเดิม")).toBeInTheDocument();

    await user.upload(screen.getByLabelText("เลือกไฟล์สำหรับนำเข้าข้อมูลเดิม"), makeTestFile("legacy-history.xlsx"));
    expect(await screen.findByText("legacy-history.xlsx")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ตรวจสอบข้อมูล" })).toBeEnabled();
  });

  describe("file type validation", () => {
    it("accepts a valid .xlsx file", async () => {
      const user = userEvent.setup();
      renderPage();

      await user.click(screen.getByLabelText(/ข้อมูลหลักเครื่องมือ/));
      await user.click(screen.getByRole("button", { name: "ถัดไป" }));
      await user.upload(screen.getByLabelText("เลือกไฟล์สำหรับนำเข้าข้อมูลเดิม"), makeTestFile("valid.xlsx"));

      expect(await screen.findByText("valid.xlsx")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "ตรวจสอบข้อมูล" })).toBeEnabled();
    });

    it.each([
      ["legacy.xls", "application/vnd.ms-excel"],
      ["data.csv", "text/csv"],
      ["scan.pdf", "application/pdf"],
      ["renamed.txt", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
    ])("rejects %s with an accessible Thai error and keeps continue disabled", async (name, type) => {
      const user = userEvent.setup({ applyAccept: false });
      renderPage();

      await user.click(screen.getByLabelText(/ข้อมูลหลักเครื่องมือ/));
      await user.click(screen.getByRole("button", { name: "ถัดไป" }));

      const rejected = new File([new Uint8Array(10)], name, { type });
      await user.upload(screen.getByLabelText("เลือกไฟล์สำหรับนำเข้าข้อมูลเดิม"), rejected);

      expect(await screen.findByRole("alert")).toHaveTextContent("รองรับเฉพาะไฟล์ .xlsx เท่านั้น");
      expect(screen.queryByText(name)).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "ตรวจสอบข้อมูล" })).toBeDisabled();
    });
  });

  describe("legacy_transaction_history migration authority flow", () => {
    beforeEach(() => {
      createLegacyHistorySession.mockResolvedValue({ id: "33333333-3333-4333-8333-333333333333" });
      uploadLegacyHistorySource.mockResolvedValue({ id: "source-1", checksum: "a".repeat(64) });
    });

    async function getToAuthorityCheck(user: ReturnType<typeof userEvent.setup>) {
      await user.click(screen.getByLabelText(/ประวัติการรับ-ส่งเครื่องมือเดิม/));
      await user.click(screen.getByRole("button", { name: "ถัดไป" }));
      await user.upload(screen.getByLabelText("เลือกไฟล์สำหรับนำเข้าข้อมูลเดิม"), makeTestFile());
      await screen.findByText("legacy-history.xlsx");
      await user.click(screen.getByRole("button", { name: "ตรวจสอบข้อมูล" }));
    }

    it("creates a real session, uploads through the real API, and navigates straight to the session when the checksum is already approved", async () => {
      findLegacyMigrationAuthorityByChecksum.mockResolvedValue({
        id: "auth-1",
        scope: "pr21_legacy_transaction_history_v1",
        approved_workbook_sha256: "a".repeat(64),
        approved_by_user_id: "user-1",
        approved_at: "2026-08-01T00:00:00Z",
        created_at: "2026-08-01T00:00:00Z",
      });
      const user = userEvent.setup();
      renderPage();

      await getToAuthorityCheck(user);

      await waitFor(() => expect(uploadLegacyHistorySource).toHaveBeenCalledTimes(1));
      expect(createLegacyHistorySession).toHaveBeenCalledTimes(1);
      expect(findLegacyMigrationAuthorityByChecksum).toHaveBeenCalledWith("a".repeat(64));
      expect(await screen.findByText("session detail page")).toBeInTheDocument();
      expect(approveLegacyMigrationAuthority).not.toHaveBeenCalled();
    });

    it("shows an explicit, never-auto-approved approval step when the checksum has not been approved yet", async () => {
      findLegacyMigrationAuthorityByChecksum.mockResolvedValue(null);
      const user = userEvent.setup();
      renderPage();

      await getToAuthorityCheck(user);

      expect(await screen.findByText("อนุมัติไฟล์สำหรับนำเข้าประวัติการรับ-ส่งเครื่องมือเดิม")).toBeInTheDocument();
      expect(approveLegacyMigrationAuthority).not.toHaveBeenCalled();
      expect(screen.queryByText("session detail page")).not.toBeInTheDocument();
    });

    it("requires an explicit confirmation dialog before approving, then navigates to the session", async () => {
      findLegacyMigrationAuthorityByChecksum.mockResolvedValue(null);
      approveLegacyMigrationAuthority.mockResolvedValue({
        authority: {
          id: "auth-2",
          scope: "pr21_legacy_transaction_history_v1",
          approved_workbook_sha256: "a".repeat(64),
          approved_by_user_id: "user-1",
          approved_at: "2026-08-01T00:00:00Z",
          created_at: "2026-08-01T00:00:00Z",
        },
        created: true,
      });
      const user = userEvent.setup();
      renderPage();

      await getToAuthorityCheck(user);
      await screen.findByText("อนุมัติไฟล์สำหรับนำเข้าประวัติการรับ-ส่งเครื่องมือเดิม");

      await user.click(screen.getByRole("button", { name: "อนุมัติไฟล์นี้" }));
      const dialog = await screen.findByRole("alertdialog");
      expect(approveLegacyMigrationAuthority).not.toHaveBeenCalled();

      await user.click(within(dialog).getByRole("button", { name: "อนุมัติ" }));

      await waitFor(() => expect(approveLegacyMigrationAuthority).toHaveBeenCalledWith("a".repeat(64)));
      expect(await screen.findByText("session detail page")).toBeInTheDocument();
    });

    it("cancelling the approval dialog never calls approve", async () => {
      findLegacyMigrationAuthorityByChecksum.mockResolvedValue(null);
      const user = userEvent.setup();
      renderPage();

      await getToAuthorityCheck(user);
      await screen.findByText("อนุมัติไฟล์สำหรับนำเข้าประวัติการรับ-ส่งเครื่องมือเดิม");
      await user.click(screen.getByRole("button", { name: "อนุมัติไฟล์นี้" }));
      const dialog = await screen.findByRole("alertdialog");
      await user.click(within(dialog).getByRole("button", { name: "ยกเลิก" }));

      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
      expect(approveLegacyMigrationAuthority).not.toHaveBeenCalled();
    });

    it("shows a Thai error message and stays on the approval step when the approve call fails", async () => {
      findLegacyMigrationAuthorityByChecksum.mockResolvedValue(null);
      approveLegacyMigrationAuthority.mockRejectedValue(new Error("network error"));
      const user = userEvent.setup();
      renderPage();

      await getToAuthorityCheck(user);
      await screen.findByText("อนุมัติไฟล์สำหรับนำเข้าประวัติการรับ-ส่งเครื่องมือเดิม");
      await user.click(screen.getByRole("button", { name: "อนุมัติไฟล์นี้" }));
      const dialog = await screen.findByRole("alertdialog");
      await user.click(within(dialog).getByRole("button", { name: "อนุมัติ" }));

      expect(await screen.findByRole("alert")).toBeInTheDocument();
      expect(screen.getByText("อนุมัติไฟล์สำหรับนำเข้าประวัติการรับ-ส่งเครื่องมือเดิม")).toBeInTheDocument();
    });
  });
});
