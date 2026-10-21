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
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      theme: "system",
      setTheme: (theme) => set({ theme }),
      lastWard: null,
      setLastWard: (ward) => set({ lastWard: ward }),
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
