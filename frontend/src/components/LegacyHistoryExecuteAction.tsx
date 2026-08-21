import { useState } from "react";

import type { LegacyHistoryDryRunPlanSummaryOut } from "@/types/legacyImportApi";

interface LegacyHistoryExecuteActionProps {
  summary: LegacyHistoryDryRunPlanSummaryOut;
  onExecute: () => void;
  executing: boolean;
}

// Roadmap PR21E: the actual "write the confirmed Issue/Receive events"
// action -- gated by its own confirmation dialog (never implicit), and by
// a disabled/loading state that prevents a repeated tap while the request
// is in flight. Mirrors EquipmentMasterExecuteAction's identical pattern.
// Never shows success optimistically -- the caller only renders a result
// once the backend has actually responded (see LegacyHistoryWorkflowPanel).
export function LegacyHistoryExecuteAction({ summary, onExecute, executing }: LegacyHistoryExecuteActionProps) {
  const [dialogOpen, setDialogOpen] = useState(false);

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={() => setDialogOpen(true)}
        disabled={executing}
        className="w-fit rounded-lg bg-status-borrowed px-4 py-2.5 font-medium text-white disabled:opacity-50"
      >
        {executing ? "กำลังนำเข้าข้อมูลจริง..." : "ดำเนินการนำเข้าจริง"}
      </button>
      {executing && (
        <p role="status" aria-live="polite" className="text-xs text-[var(--text-muted)]">
          กำลังบันทึกข้อมูลลงระบบ กรุณาอย่าปิดหน้าจอนี้จนกว่าจะเสร็จสิ้น
        </p>
      )}

      {dialogOpen && (
        <div
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="execute-legacy-history-dialog-title"
          aria-describedby="execute-legacy-history-dialog-body"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
        >
          <div className="surface w-full max-w-md rounded-xl border p-4">
            <h4 id="execute-legacy-history-dialog-title" className="text-base font-semibold">
              ยืนยันการนำเข้าข้อมูลประวัติเดิมจริง
            </h4>
            <p id="execute-legacy-history-dialog-body" className="mt-2 text-sm text-[var(--text-muted)]">
              การดำเนินการนี้จะ <strong>บันทึกประวัติการรับ-ส่งเครื่องมือเดิมลงระบบทันที</strong> ตามแผนที่ยืนยันไว้ —
              ส่งเครื่อง {summary.issue_events.toLocaleString()} รายการ และรับเครื่อง {summary.receive_events.toLocaleString()}{" "}
              รายการ ไม่สามารถยกเลิกได้หลังจากเริ่มดำเนินการ (การนำเข้านี้ไม่เปลี่ยนแปลงสถานะเครื่องมือปัจจุบัน)
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setDialogOpen(false)}
                className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
              >
                ยกเลิก
              </button>
              <button
                type="button"
                onClick={() => {
                  setDialogOpen(false);
                  onExecute();
                }}
                className="rounded-lg bg-status-borrowed px-3 py-2 text-sm font-medium text-white"
              >
                ยืนยันดำเนินการ
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
