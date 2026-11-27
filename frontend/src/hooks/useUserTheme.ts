import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { applyPreferences, cachePreferences, sanitize, type UiPreferences } from "@/lib/theme";
import { fetchPreferences, savePreferences } from "@/services/preferences";
import { useAuthStore } from "@/store/authStore";

export const PREFS_KEY = ["ui-preferences"];

/** The signed-in account's theme: fetched once, applied to :root and cached for instant paint. */
export function useUserTheme() {
  const authed = Boolean(useAuthStore((s) => s.accessToken));
  const query = useQuery({
    queryKey: PREFS_KEY,
    queryFn: async () => sanitize(await fetchPreferences()),
    enabled: authed,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
  useEffect(() => {
    // On error/offline keep whatever the cache already painted.
    if (query.data) {
      applyPreferences(query.data);
      cachePreferences(query.data);
    }
  }, [query.data]);
  return { prefs: query.data ?? null, isLoading: query.isLoading };
}

export function useSaveUserTheme() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (p: UiPreferences) => savePreferences(sanitize(p)),
    onSuccess: (saved) => {
      const clean = sanitize(saved);
      qc.setQueryData(PREFS_KEY, clean);
      cachePreferences(clean);
    },
  });
}
