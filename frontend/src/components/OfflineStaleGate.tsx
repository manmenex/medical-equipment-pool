import { useEffect, useState, useSyncExternalStore } from "react";

import {
  acknowledgeStaleness,
  getStaleness,
  isStaleAcknowledged,
  STALE_THRESHOLD_MS,
  subscribeStaleAck,
  type Staleness,
} from "@/offline/staleness";

const HOURS = STALE_THRESHOLD_MS / 3_600_000;

// PR25E S4 (design 9.8): before the first offline dispatch/receipt of a
// session on a device that has not synced for N hours, a full-screen warning
// must be acknowledged; a banner stays on the form afterwards. Never blocks
// entry permanently (work must continue).
export function OfflineStaleGate() {
  const [staleness, setStaleness] = useState<Staleness | null>(null);
  const acked = useSyncExternalStore(subscribeStaleAck, isStaleAcknowledged);

  useEffect(() => {
    let live = true;
    void getStaleness().then((s) => live && setStaleness(s));
    return () => {
      live = false;
    };
  }, []);

  if (!staleness?.stale) return null;
  const message = `เครื่องนี้ไม่ได้ซิงค์มานานกว่า ${HOURS} ชั่วโมง สถานะเครื่องมือที่แสดงอาจไม่เป็นปัจจุบัน รายการที่บันทึกอาจต้องได้รับการตรวจสอบ`;
  if (acked) {
    return (
      <p role="status" className="rounded-lg bg-status-repair/10 p-3 text-sm text-status-repair">
        {message}
      </p>
    );
  }
  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="stale-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
    >
      <div className="surface max-w-sm rounded-xl border p-6">
        <h2 id="stale-title" className="mb-2 text-lg font-semibold">
          ข้อมูลในเครื่องอาจล้าสมัย
        </h2>
        <p className="mb-4 text-sm">{message}</p>
        <button
          type="button"
          onClick={acknowledgeStaleness}
          className="w-full rounded-lg bg-status-repair py-2.5 font-medium text-white"
        >
          รับทราบและดำเนินการต่อ
        </button>
      </div>
    </div>
  );
}
