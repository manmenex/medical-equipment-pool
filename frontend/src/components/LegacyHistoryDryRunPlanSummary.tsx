import { useState } from "react";

import type { LegacyHistoryDryRunPlanOut } from "@/types/legacyImportApi";
import { formatDateTimeInTimezone } from "@/utils/printFormat";

interface LegacyHistoryDryRunPlanSummaryProps {
  plan: LegacyHistoryDryRunPlanOut;
  onConfirm: () => void;
  confirming: boolean;
  alreadyConfirmed: boolean;
}

// Roadmap PR21E: the real, persisted LegacyHistoryDryRunPlan summary
// (backend/app/schemas/legacy_history_import.py's
// LegacyHistoryDryRunPlanSummaryOut) -- total/ISSUE/RECEIVE events plus
// warnings/blocking_conflicts, PR21's own insert-oriented shape, never
// labeled as Equipment Master's creates/updates/skips. Never recomputed
// here: this component only ever renders `plan.summary` as received. The
// confirm action opens an explicit confirmation dialog, mirroring
// EquipmentMasterDryRunPlanSummary's identical pattern -- confirming is a
// prerequisite for the irreversible execute step, which writes real
// Issue/Receive history.
export function LegacyHistoryDryRunPlanSummary({
  plan,
  onConfirm,
  confirming,
  alreadyConfirmed,
}: LegacyHistoryDryRunPlanSummaryProps) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const { summary } = plan;

  const cards = [
    { label: "ทั้งหมด", value: summary.total_rows, accentClassName: "text-[var(--text-primary,inherit)]" },
    { label: "ส่งเครื่อง (Issue)", value: summary.issue_events, accentClassName: "text-status-borrowed" },
    { label: "รับเครื่อง (Receive)", value: summary.receive_events, accentClassName: "text-status-available" },
    { label: "คำเตือน", value: summary.warnings, accentClassName: "text-status-pm" },
    { label: "รายการที่ปิดกั้น", value: summary.blocking_conflicts, accentClassName: "text-status-repair" },
  ];

  return (
    <div className="flex flex-col gap-3">
      <h3 className="text-sm font-semibold">แผนการนำเข้า (ทดลองนำเข้าโดยยังไม่บันทึก)</h3>
      <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs text-[var(--text-muted)]">รหัสแผนการนำเข้า</dt>
          <dd className="break-all font-mono text-xs">{plan.id}</dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--text-muted)]">เวลาที่สร้างแผน</dt>
          <dd>{formatDateTimeInTimezone(plan.created_at, "Asia/Bangkok")}</dd>
        </div>
      </dl>
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
        (การนำเข้านี้ไม่เปลี่ยนแปลงสถานะเครื่องมือปัจจุบัน เป็นเพียงการบันทึกประวัติเดิม)
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
          aria-labelledby="confirm-legacy-history-plan-dialog-title"
          aria-describedby="confirm-legacy-history-plan-dialog-body"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
        >
          <div className="surface w-full max-w-md rounded-xl border p-4">
            <h4 id="confirm-legacy-history-plan-dialog-title" className="text-base font-semibold">
              ยืนยันแผนการนำเข้าข้อมูลประวัติเดิม
            </h4>
            <p id="confirm-legacy-history-plan-dialog-body" className="mt-2 text-sm text-[var(--text-muted)]">
              การยืนยันนี้จะล็อกแผนการนำเข้านี้ไว้สำหรับการดำเนินการนำเข้าจริงในขั้นตอนถัดไป — บันทึกประวัติส่งเครื่อง{" "}
              {summary.issue_events.toLocaleString()} รายการ และประวัติรับเครื่อง {summary.receive_events.toLocaleString()}{" "}
              รายการ (คำเตือน {summary.warnings.toLocaleString()} รายการ) การนำเข้านี้ไม่เปลี่ยนแปลงสถานะเครื่องมือปัจจุบัน
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
