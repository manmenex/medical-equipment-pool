import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProtectedRoute } from "@/components/ProtectedRoute";
import { ChangePasswordPage } from "@/pages/ChangePasswordPage";
import type { UserProfile } from "@/types";

const changePassword = vi.fn();
vi.mock("@/services/auth", () => ({
  changePassword: (...args: unknown[]) => changePassword(...args),
}));

// Vitest 2 takes the whole function signature as one type argument; the
// older `vi.fn<[Args], Return>()` form was removed and `tsc -b` rejects it
// even though `tsc --noEmit` on the app tsconfig alone does not see it.
const mockUser = vi.fn<() => UserProfile | null>();
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: mockUser(), isAuthenticated: true, isLoading: false }),
}));

vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector: (s: { accessToken: string | null }) => unknown) =>
    selector({ accessToken: "token" }),
}));

function makeUser(mustChange: boolean): UserProfile {
  return {
    id: "u1",
    employee_code: "U001",
    full_name: "Test User",
    email: "u@test.dev",
    role: "administrator",
    permissions: {},
    must_change_password: mustChange,
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/change-password"]}>
        <Routes>
          <Route path="/change-password" element={<ChangePasswordPage />} />
          <Route path="/" element={<div>dashboard</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ChangePasswordPage", () => {
  beforeEach(() => {
    changePassword.mockReset();
    mockUser.mockReset();
    mockUser.mockReturnValue(makeUser(false));
  });

  it("explains why, when the change is forced", () => {
    mockUser.mockReturnValue(makeUser(true));
    renderPage();
    expect(screen.getByRole("alert")).toHaveTextContent("ต้องเปลี่ยนรหัสผ่านก่อนใช้งาน");
  });

  it("does not nag a user who came here voluntarily", () => {
    renderPage();
    expect(screen.queryByText("ต้องเปลี่ยนรหัสผ่านก่อนใช้งาน")).not.toBeInTheDocument();
  });

  it("refuses a mismatched confirmation without calling the API", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText("รหัสผ่านปัจจุบัน"), "current-password-1");
    await user.type(screen.getByLabelText("รหัสผ่านใหม่"), "Correct-Horse-Battery-9");
    await user.type(screen.getByLabelText("ยืนยันรหัสผ่านใหม่"), "Correct-Horse-Battery-8");
    await user.click(screen.getByRole("button", { name: "เปลี่ยนรหัสผ่าน" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("ไม่ตรงกัน");
    expect(changePassword).not.toHaveBeenCalled();
  });

  it("refuses a too-short password without calling the API", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText("รหัสผ่านปัจจุบัน"), "current-password-1");
    await user.type(screen.getByLabelText("รหัสผ่านใหม่"), "abc12");
    await user.type(screen.getByLabelText("ยืนยันรหัสผ่านใหม่"), "abc12");
    await user.click(screen.getByRole("button", { name: "เปลี่ยนรหัสผ่าน" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("อย่างน้อย 6");
    expect(changePassword).not.toHaveBeenCalled();
  });

  it("counts the maximum in bytes, so a Thai passphrase is measured correctly", async () => {
    // 25 Thai characters is 75 UTF-8 bytes -- over bcrypt's 72-byte limit
    // even though it is far short of 72 *characters*. Checking `.length`
    // here would send it to the backend, which must then refuse it.
    const thai = "ก".repeat(25);
    expect(thai.length).toBe(25);
    expect(new TextEncoder().encode(thai).length).toBe(75);

    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText("รหัสผ่านปัจจุบัน"), "current-password-1");
    await user.type(screen.getByLabelText("รหัสผ่านใหม่"), thai);
    await user.type(screen.getByLabelText("ยืนยันรหัสผ่านใหม่"), thai);
    await user.click(screen.getByRole("button", { name: "เปลี่ยนรหัสผ่าน" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("72 ไบต์");
    expect(changePassword).not.toHaveBeenCalled();
  });

  it("accepts a Thai passphrase that fits inside the byte limit", async () => {
    // 24 Thai characters is exactly 72 bytes -- the limit must be reachable,
    // not merely approached.
    const thai = "ก".repeat(24);
    expect(new TextEncoder().encode(thai).length).toBe(72);

    const user = userEvent.setup();
    changePassword.mockResolvedValue(undefined);
    renderPage();
    await user.type(screen.getByLabelText("รหัสผ่านปัจจุบัน"), "current-password-1");
    await user.type(screen.getByLabelText("รหัสผ่านใหม่"), thai);
    await user.type(screen.getByLabelText("ยืนยันรหัสผ่านใหม่"), thai);
    await user.click(screen.getByRole("button", { name: "เปลี่ยนรหัสผ่าน" }));

    await waitFor(() =>
      expect(changePassword).toHaveBeenCalledWith("current-password-1", thai),
    );
  });

  it("submits both passwords and leaves the page on success", async () => {
    const user = userEvent.setup();
    changePassword.mockResolvedValue(undefined);
    renderPage();
    await user.type(screen.getByLabelText("รหัสผ่านปัจจุบัน"), "current-password-1");
    await user.type(screen.getByLabelText("รหัสผ่านใหม่"), "Correct-Horse-Battery-9");
    await user.type(screen.getByLabelText("ยืนยันรหัสผ่านใหม่"), "Correct-Horse-Battery-9");
    await user.click(screen.getByRole("button", { name: "เปลี่ยนรหัสผ่าน" }));

    await waitFor(() =>
      expect(changePassword).toHaveBeenCalledWith("current-password-1", "Correct-Horse-Battery-9"),
    );
    expect(await screen.findByText("dashboard")).toBeInTheDocument();
  });

  it("says which thing was wrong when the backend rejects it", async () => {
    const user = userEvent.setup();
    changePassword.mockRejectedValue({ response: { data: { code: "INVALID_CREDENTIALS" } } });
    renderPage();
    await user.type(screen.getByLabelText("รหัสผ่านปัจจุบัน"), "wrong-current-pass");
    await user.type(screen.getByLabelText("รหัสผ่านใหม่"), "Correct-Horse-Battery-9");
    await user.type(screen.getByLabelText("ยืนยันรหัสผ่านใหม่"), "Correct-Horse-Battery-9");
    await user.click(screen.getByRole("button", { name: "เปลี่ยนรหัสผ่าน" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("รหัสผ่านปัจจุบันไม่ถูกต้อง");
    // Still on the form -- a failed change must not look like a success.
    expect(screen.queryByText("dashboard")).not.toBeInTheDocument();
  });
});

describe("ProtectedRoute forced-change guard", () => {
  beforeEach(() => {
    mockUser.mockReset();
  });

  function renderGuard(initial: string) {
    return render(
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route
            path="/change-password"
            element={
              <ProtectedRoute>
                <div>change password page</div>
              </ProtectedRoute>
            }
          />
          <Route
            path="/equipment"
            element={
              <ProtectedRoute>
                <div>equipment page</div>
              </ProtectedRoute>
            }
          />
        </Routes>
      </MemoryRouter>,
    );
  }

  it("sends a user who must change their password to the change screen", () => {
    mockUser.mockReturnValue(makeUser(true));
    renderGuard("/equipment");
    expect(screen.getByText("change password page")).toBeInTheDocument();
  });

  it("does not redirect the change screen to itself", () => {
    mockUser.mockReturnValue(makeUser(true));
    renderGuard("/change-password");
    expect(screen.getByText("change password page")).toBeInTheDocument();
  });

  it("leaves everyone else alone", () => {
    mockUser.mockReturnValue(makeUser(false));
    renderGuard("/equipment");
    expect(screen.getByText("equipment page")).toBeInTheDocument();
  });

  it("does not redirect while the profile is still loading", () => {
    // Otherwise every authenticated user would be bounced through the
    // change-password screen on every cold load.
    mockUser.mockReturnValue(null);
    renderGuard("/equipment");
    expect(screen.getByText("equipment page")).toBeInTheDocument();
  });
});
