import { useEffect, useState } from "react";

import { useOfflineMode } from "@/hooks/useOfflineMode";
import { countMyConflicts, countMyUnsent } from "@/offline/localOps";
import { subscribeSync } from "@/offline/syncWorker";
import { useAuthStore } from "@/store/authStore";

// PR25E S4 (design 14): connection chip + pending badge. Polls the local
// outbox count (cheap IndexedDB read) and on every sync state change.
export function OfflineStatusChip() {
  const offline = useOfflineMode();
  const userId = useAuthStore((s) => s.user?.id);
  const [pending, setPending] = useState(0);
  const [conflicts, setConflicts] = useState(0);

  useEffect(() => {
    let live = true;
    const refresh = () => {
      void countMyUnsent()
        .then((n) => live && setPending(n))
        .catch(() => undefined);
      void countMyConflicts()
        .then((n) => live && setConflicts(n))
        .catch(() => undefined);
    };
    refresh();
    const unsub = subscribeSync(refresh);
    const timer = setInterval(refresh, 5_000);
    return () => {
      live = false;
      unsub();
      clearInterval(timer);
    };
  }, [userId, offline]);

  return (
    <div className="flex items-center gap-2 text-xs">
      {offline && (
        <span className="rounded-full bg-status-repair/15 px-2 py-0.5 text-status-repair">
          เซิร์ฟเวอร์ไม่พร้อม — ทำงานแบบออฟไลน์
        </span>
      )}
      {pending > 0 && (
        <span className="rounded-full bg-status-borrowed/15 px-2 py-0.5 text-status-borrowed">
          รอส่ง {pending} รายการ
        </span>
      )}
      {conflicts > 0 && (
        <span className="rounded-full bg-status-repair/15 px-2 py-0.5 text-status-repair">
          รอเจ้าหน้าที่ตรวจสอบ {conflicts} รายการ
        </span>
      )}
    </div>
  );
}
