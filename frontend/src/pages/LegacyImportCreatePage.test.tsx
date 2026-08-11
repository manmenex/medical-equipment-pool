import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LegacyImportCreatePage } from "@/pages/LegacyImportCreatePage";
import { api } from "@/services/api";
import type { UserProfile } from "@/types";

const createPreviewSession = vi.fn();
vi.mock("@/services/legacyImportClient", () => ({
  legacyImportClient: {
    createPreviewSession: (...args: unknown[]) => createPreviewSession(...args),
  },
  ImportSessionNotFoundError: class ImportSessionNotFoundError extends Error {},
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
  vi.clearAllMocks();
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

function makeTestFile(name = "receive.xlsx", sizeBytes = 2048): File {
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

    await user.click(screen.getByLabelText(/ประวัติการรับคืน/));
    expect(next).toBeEnabled();

    await user.click(next);
    expect(await screen.findByLabelText("เลือกไฟล์สำหรับนำเข้าข้อมูลเดิม")).toBeInTheDocument();
  });

  it("keeps ตรวจสอบข้อมูล disabled until a file is selected, then shows the selected file summary", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByLabelText(/ประวัติการรับคืน/));
    await user.click(screen.getByRole("button", { name: "ถัดไป" }));

    const continueButton = screen.getByRole("button", { name: "ตรวจสอบข้อมูล" });
    expect(continueButton).toBeDisabled();

    const input = screen.getByLabelText("เลือกไฟล์สำหรับนำเข้าข้อมูลเดิม");
    await user.upload(input, makeTestFile());

    expect(await screen.findByText("receive.xlsx")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ตรวจสอบข้อมูล" })).toBeEnabled();
  });

  it("replace/remove clears the selected file and disables continue again", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByLabelText(/ประวัติการรับคืน/));
    await user.click(screen.getByRole("button", { name: "ถัดไป" }));
    await user.upload(screen.getByLabelText("เลือกไฟล์สำหรับนำเข้าข้อมูลเดิม"), makeTestFile());
    await screen.findByText("receive.xlsx");

    await user.click(screen.getByRole("button", { name: "เปลี่ยนไฟล์" }));

    expect(screen.queryByText("receive.xlsx")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ตรวจสอบข้อมูล" })).toBeDisabled();
  });

  it("continuing sends only name/size/type to the mock client, never uploads, never calls the real API, and navigates to the created session", async () => {
    createPreviewSession.mockResolvedValue({ id: "preview-1" });
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByLabelText(/ประวัติการรับคืน/));
    await user.click(screen.getByRole("button", { name: "ถัดไป" }));
    await user.upload(screen.getByLabelText("เลือกไฟล์สำหรับนำเข้าข้อมูลเดิม"), makeTestFile("receive.xlsx", 2048));
    await screen.findByText("receive.xlsx");

    await user.click(screen.getByRole("button", { name: "ตรวจสอบข้อมูล" }));

    await waitFor(() => expect(createPreviewSession).toHaveBeenCalledTimes(1));
    expect(createPreviewSession).toHaveBeenCalledWith(
      expect.objectContaining({
        importCategory: "receive_history",
        file: {
          name: "receive.xlsx",
          sizeBytes: 2048,
          type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        },
      })
    );
    expect(api.post).not.toHaveBeenCalled();
    expect(api.get).not.toHaveBeenCalled();

    expect(await screen.findByText("session detail page")).toBeInTheDocument();
  });

  it("shows a back-navigation control between steps", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByLabelText(/ประวัติการรับคืน/));
    await user.click(screen.getByRole("button", { name: "ถัดไป" }));
    expect(screen.getByLabelText("เลือกไฟล์สำหรับนำเข้าข้อมูลเดิม")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "ย้อนกลับ" }));
    expect(screen.getByRole("button", { name: "ถัดไป" })).toBeInTheDocument();
  });

  it('states execution is unavailable in this skeleton', async () => {
    renderPage();
    expect(screen.getByText(/ยังไม่มีการอัปโหลด ตรวจสอบ หรือนำเข้าข้อมูลจริง/)).toBeInTheDocument();
  });

  // Bug-fix regression: switching import category after a file was already
  // selected must not silently carry that file over to the new category --
  // it must clear the file, any file-related error, and re-disable
  // ตรวจสอบข้อมูล until a new valid file is chosen for the new category.
  it("clears the selected file, its error state, and re-disables continue when the category changes", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByLabelText(/ประวัติการรับคืน/));
    await user.click(screen.getByRole("button", { name: "ถัดไป" }));
    await user.upload(screen.getByLabelText("เลือกไฟล์สำหรับนำเข้าข้อมูลเดิม"), makeTestFile());
    await screen.findByText("receive.xlsx");
    expect(screen.getByRole("button", { name: "ตรวจสอบข้อมูล" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "ย้อนกลับ" }));
    await user.click(screen.getByLabelText(/ข้อมูลหลักเครื่องมือ/));
    await user.click(screen.getByRole("button", { name: "ถัดไป" }));

    expect(screen.queryByText("receive.xlsx")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ตรวจสอบข้อมูล" })).toBeDisabled();
    expect(screen.getByLabelText("เลือกไฟล์สำหรับนำเข้าข้อมูลเดิม")).toBeInTheDocument();

    await user.upload(screen.getByLabelText("เลือกไฟล์สำหรับนำเข้าข้อมูลเดิม"), makeTestFile("equipment.xlsx"));
    expect(await screen.findByText("equipment.xlsx")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ตรวจสอบข้อมูล" })).toBeEnabled();
  });

  // Bug-fix regression: file-type enforcement must not rely on the input's
  // `accept` attribute alone (unenforced for drag-and-drop / "all files"
  // picker) -- both the extension gate and Thai error message must be
  // exercised, with full recovery after an invalid selection.
  describe("file type validation", () => {
    it("accepts a valid .xlsx file", async () => {
      const user = userEvent.setup();
      renderPage();

      await user.click(screen.getByLabelText(/ประวัติการรับคืน/));
      await user.click(screen.getByRole("button", { name: "ถัดไป" }));
      await user.upload(screen.getByLabelText("เลือกไฟล์สำหรับนำเข้าข้อมูลเดิม"), makeTestFile("valid.xlsx"));

      expect(await screen.findByText("valid.xlsx")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "ตรวจสอบข้อมูล" })).toBeEnabled();
    });

    it.each([
      ["legacy.xls", "application/vnd.ms-excel"],
      ["data.csv", "text/csv"],
      ["scan.pdf", "application/pdf"],
      // Misleading MIME: an xlsx content-type on a non-.xlsx filename must
      // still be rejected -- the extension check is authoritative, not the
      // browser-supplied MIME type.
      ["renamed.txt", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
    ])("rejects %s with an accessible Thai error and keeps continue disabled", async (name, type) => {
      // applyAccept: false simulates what the `accept` attribute cannot
      // prevent in a real browser -- picking a non-matching file via "all
      // files" in the native dialog. The dropzone's own isAllowedImportFile
      // gate (not the browser) must be what actually rejects this file.
      const user = userEvent.setup({ applyAccept: false });
      renderPage();

      await user.click(screen.getByLabelText(/ประวัติการรับคืน/));
      await user.click(screen.getByRole("button", { name: "ถัดไป" }));

      const rejected = new File([new Uint8Array(10)], name, { type });
      await user.upload(screen.getByLabelText("เลือกไฟล์สำหรับนำเข้าข้อมูลเดิม"), rejected);

      expect(await screen.findByRole("alert")).toHaveTextContent("รองรับเฉพาะไฟล์ .xlsx เท่านั้น");
      expect(screen.queryByText(name)).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "ตรวจสอบข้อมูล" })).toBeDisabled();
    });

    it("recovers after an invalid file by accepting a subsequently selected valid .xlsx file", async () => {
      const user = userEvent.setup({ applyAccept: false });
      renderPage();

      await user.click(screen.getByLabelText(/ประวัติการรับคืน/));
      await user.click(screen.getByRole("button", { name: "ถัดไป" }));

      const input = screen.getByLabelText("เลือกไฟล์สำหรับนำเข้าข้อมูลเดิม");
      await user.upload(input, new File([new Uint8Array(10)], "bad.csv", { type: "text/csv" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("รองรับเฉพาะไฟล์ .xlsx เท่านั้น");

      await user.upload(input, makeTestFile("recovered.xlsx"));

      expect(await screen.findByText("recovered.xlsx")).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "ตรวจสอบข้อมูล" })).toBeEnabled();
    });
  });
});
