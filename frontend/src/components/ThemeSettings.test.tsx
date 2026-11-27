import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeSettings } from "@/components/ThemeSettings";
import { applyPreferences, contrastRatio, contrastWarning, deriveVars } from "@/lib/theme";
import { useAuthStore } from "@/store/authStore";

const fetchPreferences = vi.fn();
const savePreferences = vi.fn();
vi.mock("@/services/preferences", () => ({
  fetchPreferences: (...a: unknown[]) => fetchPreferences(...a),
  savePreferences: (...a: unknown[]) => savePreferences(...a),
}));

function renderIt() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeSettings />
    </QueryClientProvider>,
  );
}
const rootVar = (n: string) => document.documentElement.style.getPropertyValue(n);

describe("theme library", () => {
  beforeEach(() => applyPreferences(null));

  it("applies custom colours, font size and family as :root variables", () => {
    applyPreferences({ mode: "custom", bg: "#F5EFE0", surface: "#FBF7EE", text: "#2B2B2B", accent: "#8A5A2B", font_size: 18, font_family: "serif" });
    expect(rootVar("--bg")).toBe("#F5EFE0");
    expect(rootVar("--surface")).toBe("#FBF7EE");
    expect(rootVar("--text")).toBe("#2B2B2B");
    expect(rootVar("--focus")).toBe("#8A5A2B");
    expect(document.documentElement.style.fontSize).toBe("18px");
    expect(rootVar("--font-body")).toContain("serif");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("clears every override on reset and ignores invalid values", () => {
    applyPreferences({ mode: "custom", bg: "#101010", surface: "#202020", text: "#eeeeee", accent: "#ff0000", font_size: 20 });
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.style.colorScheme).toBe("dark");
    expect(rootVar("--field")).toBe("#202020");
    applyPreferences({ mode: "custom", bg: "red" } as never);
    expect(rootVar("--bg")).toBe("#e8edf4");
    applyPreferences({});
    expect(rootVar("--bg")).toBe("");
    expect(document.documentElement.style.fontSize).toBe("");
  });

  it("derives muted text that stays readable and warns on low contrast", () => {
    const v = deriveVars({ bg: "#F5EFE0", surface: "#FBF7EE", text: "#2B2B2B", accent: "#8A5A2B" });
    expect(contrastRatio(v["--text-muted"], "#FBF7EE")).toBeGreaterThanOrEqual(4.5);
    expect(contrastWarning({ bg: "#F5EFE0", surface: "#FBF7EE", text: "#2B2B2B" })).toBeNull();
    expect(contrastWarning({ bg: "#ffffff", surface: "#ffffff", text: "#cccccc" })).toMatch(/ความคมชัดต่ำ/);
  });
});

describe("ThemeSettings", () => {
  beforeEach(() => {
    localStorage.clear();
    applyPreferences(null);
    useAuthStore.setState({ accessToken: "t" });
    fetchPreferences.mockReset().mockResolvedValue({});
    savePreferences.mockReset().mockImplementation(async (p) => p);
  });

  it("previews live, warns (not blocks) on low contrast, and saves", async () => {
    renderIt();
    fireEvent.click(await screen.findByRole("button", { name: "กำหนดเอง" }));
    fireEvent.click(screen.getByRole("button", { name: "ครีม (Cream)" }));
    expect(rootVar("--bg").toLowerCase()).toBe("#f5efe0");
    expect(screen.queryByRole("alert")).toBeNull();

    fireEvent.change(screen.getByLabelText("ตัวอักษร (รหัสสี)"), { target: { value: "#F0EAD8" } });
    expect(await screen.findByRole("alert")).toHaveTextContent("ความคมชัดต่ำ");
    fireEvent.change(screen.getByLabelText("ขนาดตัวอักษร"), { target: { value: "20" } });
    expect(document.documentElement.style.fontSize).toBe("20px");

    fireEvent.click(screen.getByRole("button", { name: "บันทึก" }));
    await waitFor(() => expect(savePreferences).toHaveBeenCalled());
    expect(savePreferences.mock.calls[0][0]).toMatchObject({ mode: "custom", text: "#F0EAD8", font_size: 20 });
    await waitFor(() => expect(localStorage.getItem("mep-user-theme")).toContain("#F0EAD8"));
  });

  it("does not apply an invalid hex while typing", async () => {
    renderIt();
    fireEvent.click(await screen.findByRole("button", { name: "กำหนดเอง" }));
    const before = rootVar("--bg");
    fireEvent.change(screen.getByLabelText("พื้นหลัง (รหัสสี)"), { target: { value: "#12" } });
    expect(rootVar("--bg")).toBe(before);
    expect(screen.getByText("รูปแบบ #RRGGBB")).toBeInTheDocument();
  });

  it("resets to defaults and saves an empty theme", async () => {
    fetchPreferences.mockResolvedValue({ mode: "custom", bg: "#101010", surface: "#202020", text: "#eeeeee", accent: "#ff0000" });
    renderIt();
    await waitFor(() => expect(rootVar("--bg")).toBe("#101010"));
    fireEvent.click(screen.getByRole("button", { name: "คืนค่าเริ่มต้น" }));
    expect(rootVar("--bg")).toBe("");
    await waitFor(() => expect(savePreferences).toHaveBeenCalledWith({}));
    await waitFor(() => expect(localStorage.getItem("mep-user-theme")).toBeNull());
  });
});
