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
});
