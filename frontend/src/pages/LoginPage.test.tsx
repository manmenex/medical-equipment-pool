import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LoginPage } from "@/pages/LoginPage";

const login = vi.fn();
vi.mock("@/services/auth", () => ({
  login: (...args: unknown[]) => login(...args),
}));

vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector: (s: { setAccessToken: (t: string) => void }) => unknown) =>
    selector({ setAccessToken: () => undefined }),
}));

// The page branches on the stable `code`, so the error it receives has to
// look like a real axios error -- `apiErrorCode` returns undefined for
// anything `axios.isAxiosError` rejects, which would make a naive mock pass
// the test while the real page fell through to the generic message.
function axiosLikeError(code: string, detail: string) {
  return {
    isAxiosError: true,
    response: { data: { code, detail, status: code === "ACCOUNT_LOCKED" ? 423 : 401 } },
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>,
  );
}

async function submit(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("รหัสพนักงาน / อีเมล"), "ADMINISTRATOR001");
  await user.type(screen.getByLabelText("รหัสผ่าน"), "Password@123");
  await user.click(screen.getByRole("button", { name: /เข้าสู่ระบบ/ }));
}

describe("LoginPage lockout message", () => {
  beforeEach(() => {
    login.mockReset();
  });

  it("explains the lockout in Thai, with the wait and the way out", async () => {
    // The backend's own detail is English. A ward nurse mid-shift whose
    // password just stopped working needs to read how long to wait and what
    // to do if they have forgotten it -- otherwise this is a support call.
    login.mockRejectedValue(
      axiosLikeError(
        "ACCOUNT_LOCKED",
        "This account is temporarily locked after 5 failed sign-in attempts.",
      ),
    );
    const user = userEvent.setup();
    renderPage();
    await submit(user);

    const alert = await screen.findByText(/ถูกล็อกชั่วคราว/);
    expect(alert).toHaveTextContent("5 ครั้ง");
    expect(alert).toHaveTextContent("10 นาที");
    expect(alert).toHaveTextContent("ผู้ดูแลระบบ");
  });

  it("still shows the backend message for an ordinary wrong password", async () => {
    // The lockout branch must not swallow every other failure.
    login.mockRejectedValue(
      axiosLikeError("INVALID_CREDENTIALS", "Invalid employee code/email or password"),
    );
    const user = userEvent.setup();
    renderPage();
    await submit(user);

    await waitFor(() =>
      expect(screen.getByText(/Invalid employee code/)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/ถูกล็อกชั่วคราว/)).not.toBeInTheDocument();
  });
});
