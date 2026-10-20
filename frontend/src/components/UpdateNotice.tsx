import { useEffect, useState } from "react";

import {
  applyUpdateIfSafe,
  getUpdateState,
  subscribeUpdate,
  type UpdateBlock,
  type UpdateState,
} from "@/offline/appUpdate";
import { canInstall, promptInstall, subscribeInstall } from "@/offline/pwa";
import { getSyncState } from "@/offline/syncWorker";

const BLOCK_TEXT: Record<UpdateBlock, string> = {
  form_dirty: "มีฟอร์มที่ยังไม่ได้บันทึก กรุณาบันทึกหรือยกเลิกก่อน",
  ops_pending: "ยังมีรายการรอส่ง กรุณารอให้ส่งเสร็จก่อน",
  sync_sending: "กำลังส่งข้อมูล กรุณารอสักครู่",
  storage_unreadable: "อ่านข้อมูลที่เก็บในเครื่องไม่ได้ จึงยังไม่รีโหลด",
};

// PR25E S6 (design 13.3, 13.1): "new version" notice and install button.
// Never reloads on its own; the operator taps the button when convenient.
export function UpdateNotice() {
  const [update, setUpdate] = useState<UpdateState>(getUpdateState());
  const [block, setBlock] = useState<UpdateBlock | null>(null);
  const [installable, setInstallable] = useState(canInstall());

  useEffect(() => subscribeUpdate(setUpdate), []);
  useEffect(() => subscribeInstall(() => setInstallable(canInstall())), []);

  const apply = async () => {
    setBlock(await applyUpdateIfSafe(getSyncState().status === "running"));
  };

  if (!update.ready && !update.required && !installable) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2 text-xs" role="status">
      {(update.ready || update.required) && (
        <>
          <span>
            {update.required
              ? "ต้องอัปเดตแอปก่อนส่งข้อมูลต่อ — รายการที่บันทึกไว้ยังอยู่ครบ"
              : "มีเวอร์ชันใหม่"}
          </span>
          <button type="button" className="rounded-lg border px-2 py-1" onClick={() => void apply()}>
            อัปเดตและรีโหลด
          </button>
          {block && <span className="text-status-repair">{BLOCK_TEXT[block]}</span>}
        </>
      )}
      {installable && (
        <button type="button" className="rounded-lg border px-2 py-1" onClick={() => void promptInstall()}>
          ติดตั้งแอปบนเครื่องนี้
        </button>
      )}
    </div>
  );
}
