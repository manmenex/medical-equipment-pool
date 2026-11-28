import { create } from "zustand";
import { persist } from "zustand/middleware";

type Theme = "light" | "dark" | "system";

interface UiState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  lastWard: string | null;
  // Roadmap PR7b: borrower_name is no longer accepted by the dispatch
  // write path, so there is nothing to remember here anymore.
  setLastWard: (ward: string | null) => void;
  // Roadmap PR27/PR28: per-ward use counts (local history only) for the
  // "most used wards" chips on the dispatch/receipt screens.
  wardUsage: Record<string, number>;
  bumpWardUsage: (ward: string) => void;
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      theme: "system",
      setTheme: (theme) => set({ theme }),
      lastWard: null,
      setLastWard: (ward) => set({ lastWard: ward }),
      wardUsage: {},
      bumpWardUsage: (ward) => set((s) => ({ wardUsage: { ...s.wardUsage, [ward]: (s.wardUsage[ward] ?? 0) + 1 } })),
    }),
    { name: "mep-ui" }
  )
);

export function applyTheme(theme: Theme) {
  const root = document.documentElement;
  const isDark =
    theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  root.classList.toggle("dark", isDark);
}
