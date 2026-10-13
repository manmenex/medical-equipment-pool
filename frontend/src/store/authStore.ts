import { create } from "zustand";
import { persist } from "zustand/middleware";

import { queryClient } from "@/lib/queryClient";
import type { UserProfile } from "@/types";

interface AuthState {
  accessToken: string | null;
  user: UserProfile | null;
  setAccessToken: (token: string | null) => void;
  setUser: (user: UserProfile | null) => void;
  logout: () => void;
}

// Logout wipes cached server data: React Query and Cache Storage (including
// the service worker's API cache). Best effort; never blocks logout.
function wipeCachedData(): void {
  try {
    queryClient.clear();
  } catch {
    /* ignore */
  }
  try {
    if (typeof caches !== "undefined") {
      void caches
        .keys()
        .then((keys) => Promise.all(keys.filter((k) => k.includes("api")).map((k) => caches.delete(k))))
        .catch(() => undefined);
    }
  } catch {
    /* ignore */
  }
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      user: null,
      setAccessToken: (token) => set({ accessToken: token }),
      setUser: (user) => set({ user }),
      logout: () => {
        set({ accessToken: null, user: null });
        wipeCachedData();
      },
    }),
    { name: "mep-auth" }
  )
);
