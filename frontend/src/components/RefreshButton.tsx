import { useEffect, useState } from "react";

import { useOfflineMode } from "@/hooks/useOfflineMode";
import {
  applyUpdateNow,
  getUpdateState,
  subscribeUpdate,
  updateBlockReason,
} from "@/offline/appUpdate";
import { getSyncState } from "@/offline/syncWorker";

const LABEL_UPDATE = "มีเวอร์ชันใหม่ กดเพื่ออัปเดต";
const LABEL_REFRESH = "รีเฟรช";
const CONFIRM_TEXT = "มีข้อมูลที่ยังไม่บันทึก ต้องการรีเฟรชหรือไม่?";
const LABEL_OFFLINE = "ออฟไลน์ - โหลดจากแคช";

export function RefreshButton({ reload }: { reload?: () => void }) {
  const offline = useOfflineMode();
  const [update, setUpdate] = useState(getUpdateState());
  const [waiting, setWaiting] = useState(false);
  useEffect(() => subscribeUpdate(setUpdate), []);

  // A waiting worker may exist without onNeedRefresh having fired.
  useEffect(() => {
    let live = true;
    const sw = typeof navigator !== "undefined" ? navigator.serviceWorker : undefined;
    void sw
      ?.getRegistration?.()
      .then((r) => live && setWaiting(!!r?.waiting))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [update.ready]);

  const hasUpdate = update.ready || update.required || waiting;
  const label = hasUpdate ? LABEL_UPDATE : offline ? `${LABEL_REFRESH} (${LABEL_OFFLINE})` : LABEL_REFRESH;
  const doReload = reload ?? (() => window.location.reload());

  const onClick = async () => {
    // Same guard as the update notice; here the operator may override it, but
    // only after confirming -- before update()/SKIP_WAITING can reload the page.
    const block = await updateBlockReason(getSyncState().status === "running");
    if (block && !window.confirm(CONFIRM_TEXT)) return;
    try {
      const reg = await navigator.serviceWorker?.getRegistration?.();
      if (reg) {
        if (!offline) await reg.update().catch(() => undefined);
        if (reg.waiting && !getUpdateState().ready) {
          reg.waiting.postMessage({ type: "SKIP_WAITING" });
        }
      }
    } catch {
      // fall through to reload
    }
    await applyUpdateNow(doReload);
  };

  return (
    <button
      type="button"
      data-testid="refresh-button"
      title={label}
      aria-label={label}
      onClick={() => void onClick()}
      className="relative flex h-10 w-10 items-center justify-center rounded-lg text-lg text-[var(--text-muted)] hover:bg-black/5 dark:hover:bg-white/5"
    >
      <span aria-hidden="true">⟳</span>
      {hasUpdate && (
        <span
          aria-hidden="true"
          data-testid="refresh-badge"
          className="absolute right-1.5 top-1.5 h-2.5 w-2.5 rounded-full bg-status-repair"
        />
      )}
    </button>
  );
}
