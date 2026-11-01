import { useEffect, useState } from "react";

import { isMarkedOffline, subscribeOffline } from "@/services/connectivity";

/**
 * True when the app should use the offline forms: the server was marked
 * unreachable by S1's detection, or the browser reports no network. Online
 * (the normal case) this is false and the forms use the unchanged API path.
 */
export function useOfflineMode(): boolean {
  const read = () => isMarkedOffline() || (typeof navigator !== "undefined" && navigator.onLine === false);
  const [offline, setOffline] = useState(read);
  useEffect(() => {
    const update = () => setOffline(read());
    const unsub = subscribeOffline(update);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    update();
    return () => {
      unsub();
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);
  return offline;
}
