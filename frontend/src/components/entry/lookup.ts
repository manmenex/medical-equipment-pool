import { searchCachedBcm } from "@/offline/localOps";
import { searchBcmSuggestions } from "@/services/equipment";
import type { BcmSuggestion } from "@/types";

/** Exact BCM match wins; otherwise a single suggestion is taken; else null. */
export async function resolveBcmText(text: string, offline: boolean): Promise<BcmSuggestion | null> {
  const q = text.trim();
  if (!q) return null;
  const list = offline ? await searchCachedBcm(q) : await searchBcmSuggestions(q);
  const exact = list.find((s) => s.bcm_code.trim().toLowerCase() === q.toLowerCase());
  if (exact) return exact;
  return list.length === 1 ? list[0] : null;
}
