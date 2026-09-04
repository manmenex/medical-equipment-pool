import { useState } from "react";

import type { DryRunPlanSummaryOut } from "@/types/legacyImportApi";

interface EquipmentMasterExecuteActionProps {
  summary: DryRunPlanSummaryOut;
  onExecute: () => void;
  executing: boolean;
}

// Roadmap PR20F (design §17-§19): the actual, irreversible "write to
// Equipment" action -- gated by its own confirmation dialog (never
// implicit), and by a disabled/loading state that prevents a repeated
// tap while the request is in flight. Never shows success optimistically
// -- the caller only renders a result once the backend has actually
// responded (see EquipmentMasterWorkflowPanel).
export function EquipmentMasterExecuteAction({ summary, onExecute, executing }: EquipmentMasterExecuteActionProps) {
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
          aria-labelledby="execute-dialog-title"
          aria-describedby="execute-dialog-body"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
        >
          <div className="surface w-full max-w-md rounded-xl border p-4">
            <h4 id="execute-dialog-title" className="text-base font-semibold">
              ยืนยันการนำเข้าข้อมูลจริง
            </h4>
            <p id="execute-dialog-body" className="mt-2 text-sm text-[var(--text-muted)]">
              การดำเนินการนี้จะ <strong>แก้ไขข้อมูลเครื่องมือจริงในระบบทันที</strong> ตามแผนที่ยืนยันไว้ — สร้างใหม่{" "}
              {summary.creates.toLocaleString()} รายการ และอัปเดต {summary.updates.toLocaleString()} รายการ
              ไม่สามารถยกเลิกได้หลังจากเริ่มดำเนินการ
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
