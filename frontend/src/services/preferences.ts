import { api } from "@/services/api";
import type { UiPreferences } from "@/lib/theme";

export async function fetchPreferences(): Promise<UiPreferences> {
  const resp = await api.get<UiPreferences>("/me/preferences");
  return resp.data;
}

/** Replaces the caller's theme; `{}` resets it. */
export async function savePreferences(p: UiPreferences): Promise<UiPreferences> {
  const body = Object.fromEntries(Object.entries(p).filter(([, v]) => v !== null && v !== undefined));
  const resp = await api.put<UiPreferences>("/me/preferences", body);
  return resp.data;
}
