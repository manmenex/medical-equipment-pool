import { create } from "zustand";
import { persist } from "zustand/middleware";

type Theme = "light" | "dark" | "system";

interface UiState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  lastWard: string | null;
  lastBorrowerName: string | null;
  setLastBorrow: (ward: string | null, name: string | null) => void;
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      theme: "system",
      setTheme: (theme) => set({ theme }),
      lastWard: null,
      lastBorrowerName: null,
      setLastBorrow: (ward, name) => set({ lastWard: ward, lastBorrowerName: name }),
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
