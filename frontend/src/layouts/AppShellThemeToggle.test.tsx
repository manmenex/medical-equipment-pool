import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "@/layouts/AppShell";
import { useAuthStore } from "@/store/authStore";

vi.mock("@/hooks/useAuth", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useAuth")>("@/hooks/useAuth");
  return {
    ...actual,
    useAuth: () => ({
      user: { id: "u", employee_code: "U", full_name: "T", email: "t@t", role: "read_only", permissions: {}, must_change_password: false },
      isAuthenticated: true,
      isLoading: false,
    }),
  };
});

const fetchPreferences = vi.fn();
const savePreferences = vi.fn();
vi.mock("@/services/preferences", () => ({
  fetchPreferences: (...a: unknown[]) => fetchPreferences(...a),
  savePreferences: (...a: unknown[]) => savePreferences(...a),
}));

const CUSTOM = { mode: "custom", bg: "#F5EFE0", surface: "#FBF7EE", text: "#2B2B2B", accent: "#8A5A2B", font_size: 18 };

function renderShell() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<div>home</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AppShell theme toggle", () => {
  beforeEach(() => {
    localStorage.clear();
    useAuthStore.setState({ accessToken: "t" });
    savePreferences.mockReset().mockImplementation(async (p) => p);
  });

  it("is disabled while the saved theme is loading, so it cannot overwrite it", () => {
    fetchPreferences.mockReset().mockReturnValue(new Promise(() => undefined));
    renderShell();
    expect(screen.getAllByLabelText("สลับธีมสว่าง/มืด")[0]).toBeDisabled();
  });

  it("keeps saved custom colours and font when only the mode is toggled", async () => {
    fetchPreferences.mockReset().mockResolvedValue(CUSTOM);
    renderShell();
    const btn = screen.getAllByLabelText("สลับธีมสว่าง/มืด")[0];
    await waitFor(() => expect(btn).toBeEnabled());
    fireEvent.click(btn);
    await waitFor(() => expect(savePreferences).toHaveBeenCalled());
    expect(savePreferences.mock.calls[0][0]).toMatchObject({ ...CUSTOM, mode: expect.stringMatching(/light|dark/) });
  });
});
