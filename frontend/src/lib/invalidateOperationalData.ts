import type { QueryClient } from "@tanstack/react-query";

import { queryClient as sharedClient } from "@/lib/queryClient";

// Query-key prefixes whose data changes when equipment/transaction state
// changes. Called after any dispatch, receipt, undo, D28 correction, ward
// correction or sync completion so no screen shows pre-save state.
export const OPERATIONAL_QUERY_KEYS: readonly string[] = [
  "equipment", // list, search and detail (["equipment", id, ...])
  "transactions",
  "active-borrows",
  "dashboard",
  "monitor-events",
  "monitor-count",
  "standby-summary",
  "standby-text",
  "reports", // includes ["reports", "outstanding", ...]
  "print-data",
  "cuffs-outstanding",
];

export function invalidateOperationalData(client: QueryClient = sharedClient): Promise<void[]> {
  return Promise.all(OPERATIONAL_QUERY_KEYS.map((k) => client.invalidateQueries({ queryKey: [k] })));
}
