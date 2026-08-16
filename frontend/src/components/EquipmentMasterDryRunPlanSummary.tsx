import { useState } from "react";

import type { DryRunPlanOut } from "@/types/legacyImportApi";

interface EquipmentMasterDryRunPlanSummaryProps {
  plan: DryRunPlanOut;
  onConfirm: () => void;
  confirming: boolean;
  alreadyConfirmed: boolean;
}

// Roadmap PR20F: the real, persisted DryRunPlan summary
// (backend/app/schemas/import_session.py's DryRunPlanSummaryOut) --
// creates/updates/skips/warnings/blocking_conflicts, exactly as computed
// and persisted by the backend (design §14/§14.2). Never recomputed here:
// this component only ever renders `plan.summary` as received. The
// confirm action opens an explicit confirmation dialog (design §14.4a) --
// confirming is irreversible in the sense that only a confirmed plan can
// ever be executed, and execution mutates real Equipment records.
export function EquipmentMasterDryRunPlanSummary({
  plan,
  onConfirm,
  confirming,
  alreadyConfirmed,
}: EquipmentMasterDryRunPlanSummaryProps) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const { summary } = plan;

  const cards = [
    { label: "ทั้งหมด", value: summary.total_rows, accentClassName: "text-[var(--text-primary,inherit)]" },
    { label: "สร้างใหม่", value: summary.creates, accentClassName: "text-status-available" },
    { label: "อัปเดต", value: summary.updates, accentClassName: "text-status-borrowed" },
    { label: "ข้าม", value: summary.skips, accentClassName: "text-[var(--text-muted)]" },
    { label: "คำเตือน", value: summary.warnings, accentClassName: "text-status-pm" },
    { label: "รายการที่ปิดกั้น", value: summary.blocking_conflicts, accentClassName: "text-status-repair" },
  ];

  return (
    <div className="flex flex-col gap-3">
      <h3 className="text-sm font-semibold">แผนการนำเข้า (ทดลองนำเข้าโดยยังไม่บันทึก)</h3>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {cards.map((card) => (
          <div key={card.label} className="surface flex flex-col gap-1 rounded-xl border p-3">
            <span className="text-xs text-[var(--text-muted)]">{card.label}</span>
            <span className={`text-xl font-semibold ${card.accentClassName}`}>{card.value.toLocaleString()}</span>
          </div>
        ))}
      </div>

      <div className="rounded-lg border border-[var(--border)] bg-[var(--border)]/10 p-3 text-sm">
        นี่คือแผนที่บันทึกไว้จากการทดลองนำเข้าครั้งล่าสุด ยังไม่มีการบันทึกข้อมูลลงระบบจนกว่าจะยืนยันและดำเนินการนำเข้าจริง
      </div>

      {alreadyConfirmed ? (
        <p className="text-sm font-medium text-status-available">ยืนยันแผนนี้แล้ว พร้อมดำเนินการนำเข้าจริง</p>
      ) : (
        <div>
          <button
            type="button"
            onClick={() => setDialogOpen(true)}
            disabled={confirming}
            className="w-fit rounded-lg bg-status-borrowed px-4 py-2.5 font-medium text-white disabled:opacity-50"
          >
            {confirming ? "กำลังยืนยัน..." : "ยืนยันแผนการนำเข้า"}
          </button>
        </div>
      )}

      {dialogOpen && (
        <div
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="confirm-plan-dialog-title"
          aria-describedby="confirm-plan-dialog-body"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
        >
          <div className="surface w-full max-w-md rounded-xl border p-4">
            <h4 id="confirm-plan-dialog-title" className="text-base font-semibold">
              ยืนยันแผนการนำเข้าข้อมูล
            </h4>
            <p id="confirm-plan-dialog-body" className="mt-2 text-sm text-[var(--text-muted)]">
              การยืนยันนี้จะล็อกแผนการนำเข้านี้ไว้สำหรับการดำเนินการนำเข้าจริงในขั้นตอนถัดไป ซึ่งจะ{" "}
              <strong>แก้ไขข้อมูลเครื่องมือจริงในระบบ</strong> — สร้างใหม่ {summary.creates.toLocaleString()} รายการ
              และอัปเดต {summary.updates.toLocaleString()} รายการ (ข้าม {summary.skips.toLocaleString()} รายการ,
              คำเตือน {summary.warnings.toLocaleString()} รายการ)
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
                  onConfirm();
                }}
                className="rounded-lg bg-status-borrowed px-3 py-2 text-sm font-medium text-white"
              >
                ยืนยัน
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
