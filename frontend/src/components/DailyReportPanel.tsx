import { useState } from "react";

import {
  DEFAULT_GRACE_MINUTES,
  MAX_GRACE_MINUTES,
  downloadDailySummary,
  printDailyForm,
  type DailyFormKind,
  type DailyFormShift,
} from "@/services/dailyReport";
import { currentBusinessDate } from "@/utils/shift";

// Roadmap PR30: "รายงานประจำวัน" on the Reports page. Report date D = the
// Night shift that started 20:00 on D-1 plus Day shift D (backend decides).
export function DailyReportPanel() {
  const [date, setDate] = useState(() => currentBusinessDate(new Date()));
  const [grace, setGrace] = useState(String(DEFAULT_GRACE_MINUTES));
  const [shift, setShift] = useState<DailyFormShift>("day");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const graceNumber = Number(grace);
  const graceValid =
    grace.trim() !== "" && Number.isInteger(graceNumber) && graceNumber >= 0 && graceNumber <= MAX_GRACE_MINUTES;
  const canRun = Boolean(date) && graceValid && busy === null;

  const run = async (key: string, action: () => Promise<void>) => {
    setBusy(key);
    setError(null);
    try {
      await action();
    } catch {
      setError("สร้างรายงานไม่สำเร็จ กรุณาลองใหม่อีกครั้ง");
    } finally {
      setBusy(null);
    }
  };

  const form = (kind: DailyFormKind) => () => printDailyForm(date, kind, graceNumber, shift);
  // "สรุปรวมยอด": the Day-shift forms plus the 2-shift workbook (as the pool's old tool).
  const summary = async () => {
    await downloadDailySummary(date, graceNumber);
    await printDailyForm(date, "both", graceNumber, "day");
  };
  const shiftOptions: [DailyFormShift, string][] = [
    ["day", "กะกลางวัน"],
    ["night", "กะกลางคืน"],
    ["both", "ทั้งสองกะ"],
  ];
  const buttonClass = "rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium disabled:opacity-50";

  return (
    <section className="surface rounded-xl border p-4" aria-labelledby="daily-report-title">
      <h2 id="daily-report-title" className="mb-1 text-sm font-medium">
        รายงานประจำวัน
      </h2>
      <p className="mb-3 text-xs text-[var(--text-muted,inherit)]">
        กะกลางคืนก่อนหน้า (20:00) + กะกลางวัน 08:00-20:00
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs">
          วันที่รายงาน
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          เผื่อเวลา (นาที)
          <input
            type="number"
            min={0}
            max={MAX_GRACE_MINUTES}
            step={1}
            value={grace}
            onChange={(e) => setGrace(e.target.value)}
            aria-invalid={!graceValid}
            className="w-28 rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm"
          />
        </label>
        <button className={buttonClass} disabled={!canRun} onClick={() => run("xlsx", () => downloadDailySummary(date, graceNumber))}>
          ดาวน์โหลด Excel
        </button>
        <fieldset className="flex flex-col gap-1 text-xs">
          <legend className="mb-1">ฟอร์มที่พิมพ์ (กะ)</legend>
          <div className="flex gap-3">
            {shiftOptions.map(([value, label]) => (
              <label key={value} className="flex items-center gap-1 text-sm">
                <input type="radio" name="daily-form-shift" value={value} checked={shift === value} onChange={() => setShift(value)} />
                {label}
              </label>
            ))}
          </div>
        </fieldset>
        <button className={buttonClass} disabled={!canRun} onClick={() => run("dispatch", form("dispatch"))}>
          พิมพ์ฟอร์มส่ง
        </button>
        <button className={buttonClass} disabled={!canRun} onClick={() => run("receipt", form("receipt"))}>
          พิมพ์ฟอร์มรับ
        </button>
        <button className={buttonClass} disabled={!canRun} onClick={() => run("summary", summary)}>
          สรุปรวมยอด
        </button>
      </div>
      {!graceValid && (
        <p role="alert" className="mt-2 text-xs text-red-600">
          เผื่อเวลาต้องเป็นจำนวนเต็ม 0-{MAX_GRACE_MINUTES} นาที
        </p>
      )}
      {error && (
        <p role="alert" className="mt-2 text-xs text-red-600">
          {error}
        </p>
      )}
    </section>
  );
}
