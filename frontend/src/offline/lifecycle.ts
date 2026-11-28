import { deleteLegacyApiCache, useAuthStore } from "@/store/authStore";

import { requestPersistentStorage } from "./pwa";
import { startSnapshotRefresh } from "./snapshot";
import { resetStaleAcknowledgement } from "./staleness";
import { startSyncWorker } from "./syncWorker";

/**
 * Start the offline machinery for the signed-in shell: sync worker (S3),
 * snapshot refresh (S4), and per-session staleness acknowledgement reset.
 * Also removes the retired `mep-api-cache` from devices that still hold it.
 */
export function startOfflineServices(): () => void {
  void deleteLegacyApiCache();
  void requestPersistentStorage(); // design 13.1
  const stopSync = startSyncWorker();
  const stopSnapshot = startSnapshotRefresh();
  const unsub = useAuthStore.subscribe((s, prev) => {
    if ((s.user?.id ?? null) !== (prev.user?.id ?? null)) resetStaleAcknowledgement();
  });
  return () => {
    stopSync();
    stopSnapshot();
    unsub();
  };
}
