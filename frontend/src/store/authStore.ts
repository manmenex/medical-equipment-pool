import { create } from "zustand";
import { persist } from "zustand/middleware";

import { queryClient } from "@/lib/queryClient";
import { wipeOnLogout } from "@/offline/offlineStore";
import type { UserProfile } from "@/types";

interface AuthState {
  accessToken: string | null;
  user: UserProfile | null;
  setAccessToken: (token: string | null) => void;
  setUser: (user: UserProfile | null) => void;
  logout: () => void;
}

/**
 * The Cache Storage name used by the retired Workbox runtime rule
 * (vite.config.ts, removed in PR25E S4). Matched EXACTLY: a substring match
 * ("api") would also delete unrelated caches such as the precache.
 */
export const LEGACY_API_CACHE_NAME = "mep-api-cache";

/** Delete the retired API runtime cache by exact name. Never rejects. */
export async function deleteLegacyApiCache(): Promise<void> {
  try {
    if (typeof caches === "undefined") return;
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k === LEGACY_API_CACHE_NAME).map((k) => caches.delete(k)));
  } catch {
    /* ignore */
  }
}

// Logout wipes cached server data: React Query, the IndexedDB reference
// snapshot and the legacy API cache. Best effort; never blocks logout, but the
// returned promise lets the next login wait until the wipe has finished so a
// fast re-login cannot have its fresh snapshot wiped (PR25E S4, S2 review note).
async function wipeCachedData(): Promise<void> {
  try {
    queryClient.clear();
  } catch {
    /* ignore */
  }
  // PR25E S2: clear the IndexedDB reference snapshot; unsynced outbox/journal
  // rows and device identity are deliberately kept (design 8.2).
  await wipeOnLogout().catch(() => undefined);
  await deleteLegacyApiCache();
}

let pendingWipe: Promise<void> = Promise.resolve();

/** Resolves when the most recent logout wipe has finished (immediately if none). */
export function whenLogoutWipeDone(): Promise<void> {
  return pendingWipe;
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
        pendingWipe = wipeCachedData();
      },
    }),
    { name: "mep-auth" }
  )
);
