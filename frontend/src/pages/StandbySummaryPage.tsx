import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { canDispatchOrReceiveEquipment, useAuth } from "@/hooks/useAuth";
import { apiErrorMessage } from "@/services/api";
import { DEFAULT_GRACE_MINUTES, downloadDailySummary } from "@/services/dailyReport";
import {
  fetchStandbySummary,
  fetchStandbyText,
  saveStandbyBaseline,
  saveStandbyOverride,
  type StandbyCutoff,
  type StandbyField,
  type StandbySummary,
} from "@/services/standbySummary";
import { currentBusinessDate } from "@/utils/shift";

// Roadmap PR34 (Owner Governance 2026-11-26 D16): "สรุป Stand By". Night
// summary = 08:00, Day summary = 20:00 on the chosen date. Every number is
// editable by pool staff; the system value stays visible (and restorable)
// whenever it was edited. Only counts are shown: no HN, no patient data.

const MAX_VALUE = 9999;

interface EditableNumberProps {
  field: StandbyField;
  label?: string;
  disabled: boolean;
  onSave: (key: string, value: number | null) => void;
}

/** Number input that saves on blur/Enter, with a system-value hint + reset when edited. */
export function EditableNumber({ field, label, disabled, onSave }: EditableNumberProps) {
  const shown = field.effective_value === null ? "" : String(field.effective_value);
  const [draft, setDraft] = useState(shown);
  useEffect(() => setDraft(shown), [shown]);
  const name = label ?? field.label;

  const commit = () => {
    if (draft === shown) return;
    if (draft.trim() === "") {
      setDraft(shown);
      return;
    }
    const n = Number(draft);
    if (!Number.isInteger(n) || n < 0 || n > MAX_VALUE) {
      setDraft(shown);
      return;
    }
    onSave(field.key, n);
  };

  const edited = field.override_value !== null;
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <input
        type="number"
        inputMode="numeric"
        min={0}
        max={MAX_VALUE}
        step={1}
        aria-label={name}
        value={draft}
        placeholder="-"
        disabled={disabled}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
        }}
        className={`w-20 rounded-lg border bg-transparent px-2 py-1 text-sm ${
          edited ? "border-amber-500" : "border-[var(--border)]"
        }`}
      />
      {edited && (
        <>
          <span className="text-xs text-[var(--text-muted)]" data-testid={`hint-${field.key}`}>
            ระบบ: {field.system_value ?? "-"}
          </span>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onSave(field.key, null)}
            aria-label={`คืนค่าระบบ ${name}`}
            className="rounded-md border border-[var(--border)] px-2 py-0.5 text-xs disabled:opacity-60"
          >
            คืนค่าระบบ
          </button>
        </>
      )}
    </span>
  );
}

function BaselineDialog({ summary, onClose }: { summary: StandbySummary; onClose: () => void }) {
  const queryClient = useQueryClient();
  const base = summary.infusion.baseline;
  const [chargers, setChargers] = useState(base.chargers === null ? "" : String(base.chargers));
  const [clamps, setClamps] = useState(base.clamps === null ? "" : String(base.clamps));
  const valid = (v: string) => v.trim() !== "" && Number.isInteger(Number(v)) && Number(v) >= 0 && Number(v) <= MAX_VALUE;
  const save = useMutation({
    mutationFn: () => saveStandbyBaseline(Number(chargers), Number(clamps)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["standby-summary"] });
      await queryClient.invalidateQueries({ queryKey: ["standby-text"] });
      onClose();
    },
  });
  const inputCls = "w-28 rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm";
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="baseline-title" className="surface rounded-xl border p-4">
      <h3 id="baseline-title" className="mb-1 text-sm font-medium">
        ตั้งค่าเริ่มต้น สายชาร์จ / Clamp
      </h3>
      <p className="mb-3 text-xs text-[var(--text-muted)]">
        กรอกจำนวนที่คลังจริง ณ ตอนนี้ ระบบจะบวก/ลบจากรายการเช็กสายชาร์จและ Clamp ตอนส่ง-รับ นับจากเวลาที่บันทึก
        {base.set_at ? ` (ตั้งไว้ล่าสุด ${new Date(base.set_at).toLocaleString("th-TH")})` : ""}
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs">
          สายชาร์จที่คลัง
          <input type="number" min={0} value={chargers} onChange={(e) => setChargers(e.target.value)} className={inputCls} />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          Clamp ที่คลัง
          <input type="number" min={0} value={clamps} onChange={(e) => setClamps(e.target.value)} className={inputCls} />
        </label>
        <button
          type="button"
          disabled={!valid(chargers) || !valid(clamps) || save.isPending}
          onClick={() => save.mutate()}
          className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium disabled:opacity-50"
        >
          บันทึกค่าเริ่มต้น
        </button>
        <button type="button" onClick={onClose} className="rounded-lg px-3 py-2 text-sm">
          ยกเลิก
        </button>
      </div>
      {save.isError && (
        <p role="alert" className="mt-2 text-xs text-red-600">
          {apiErrorMessage(save.error)}
        </p>
      )}
    </div>
  );
}

export function StandbySummaryPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const allowed = canDispatchOrReceiveEquipment(user);
  const [date, setDate] = useState(() => currentBusinessDate(new Date()));
  const [cutoff, setCutoff] = useState<StandbyCutoff>("night");
  const [showBaseline, setShowBaseline] = useState(false);
  const [copied, setCopied] = useState<"ok" | "fail" | null>(null);
  const [busy, setBusy] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const summaryKey = ["standby-summary", date, cutoff] as const;
  const summary = useQuery({
    queryKey: summaryKey,
    queryFn: () => fetchStandbySummary(date, cutoff),
    enabled: allowed && Boolean(date),
  });
  const text = useQuery({
    queryKey: ["standby-text", date, cutoff],
    queryFn: () => fetchStandbyText(date, cutoff),
    enabled: allowed && Boolean(date),
  });

  const edit = useMutation({
    mutationFn: ({ key, value }: { key: string; value: number | null }) =>
      saveStandbyOverride(date, cutoff, key, value),
    onSuccess: (updated) => {
      queryClient.setQueryData(summaryKey, updated);
      void queryClient.invalidateQueries({ queryKey: ["standby-text", date, cutoff] });
    },
  });
  const onSave = (key: string, value: number | null) => edit.mutate({ key, value });

  const copy = async () => {
    if (text.data === undefined) return;
    try {
      await navigator.clipboard.writeText(text.data);
      setCopied("ok");
    } catch {
      setCopied("fail");
    }
  };

  const download = async () => {
    setBusy(true);
    setDownloadError(null);
    try {
      await downloadDailySummary(date, DEFAULT_GRACE_MINUTES);
    } catch {
      setDownloadError("ดาวน์โหลดไม่สำเร็จ กรุณาลองใหม่อีกครั้ง");
    } finally {
      setBusy(false);
    }
  };

  if (!allowed) {
    return (
      <section className="p-4">
        <h1 className="text-lg font-semibold">สรุป Stand By</h1>
        <p className="mt-2 text-sm text-[var(--text-muted)]">หน้านี้สำหรับเจ้าหน้าที่ศูนย์เครื่องมือและผู้ดูแลระบบ</p>
      </section>
    );
  }

  const data = summary.data;
  const disabled = edit.isPending;
  const toggleCls = (active: boolean) =>
    `rounded-lg border px-3 py-2 text-sm font-medium ${
      active ? "border-status-borrowed bg-status-borrowed/15 text-status-borrowed" : "border-[var(--border)]"
    }`;
  const cell = "px-2 py-2 text-sm";

  return (
    <section className="flex flex-col gap-4 p-4" aria-labelledby="standby-title">
      <h1 id="standby-title" className="text-lg font-semibold">
        สรุป Stand By
      </h1>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs">
          วันที่
          <input
            type="date"
            value={date}
            onChange={(e) => {
              setDate(e.target.value);
              setCopied(null);
            }}
            className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm"
          />
        </label>
        <div role="group" aria-label="รอบสรุป" className="flex gap-2">
          <button
            type="button"
            aria-pressed={cutoff === "night"}
            className={toggleCls(cutoff === "night")}
            onClick={() => {
              setCutoff("night");
              setCopied(null);
            }}
          >
            สรุปกะ Night (08:00)
          </button>
          <button
            type="button"
            aria-pressed={cutoff === "day"}
            className={toggleCls(cutoff === "day")}
            onClick={() => {
              setCutoff("day");
              setCopied(null);
            }}
          >
            สรุปกะ Day (20:00)
          </button>
        </div>
      </div>

      {summary.isLoading && <p className="text-sm">กำลังโหลด...</p>}
      {summary.isError && (
        <p role="alert" className="text-sm text-red-600">
          โหลดสรุปไม่สำเร็จ {apiErrorMessage(summary.error)}
        </p>
      )}
      {edit.isError && (
        <p role="alert" className="text-sm text-red-600">
          บันทึกไม่สำเร็จ {apiErrorMessage(edit.error)}
        </p>
      )}

      {data && (
        <>
          <section className="surface rounded-xl border p-4" aria-labelledby="infusion-title">
            <h2 id="infusion-title" className="mb-1 text-sm font-medium">
              Infusion pump standby
            </h2>
            <p className="mb-3 text-xs text-[var(--text-muted)]">
              จำนวนเครื่องที่ส่งไปแล้วและยังไม่มี HN ณ เวลาสรุป แยกตามหอผู้ป่วย (ชื่อย่อตามรายงานประจำวัน)
            </p>
            <table className="w-full text-left">
              <thead>
                <tr className="text-xs text-[var(--text-muted)]">
                  <th className={cell}>หอผู้ป่วย</th>
                  <th className={cell}>จำนวน (เครื่อง)</th>
                </tr>
              </thead>
              <tbody>
                {data.infusion.wards.length === 0 && (
                  <tr>
                    <td className={cell} colSpan={2}>
                      ไม่มีเครื่อง Stand By ที่หอผู้ป่วย
                    </td>
                  </tr>
                )}
                {data.infusion.wards.map((w) => (
                  <tr key={w.key} className="border-t border-[var(--border)]">
                    <th scope="row" className={`${cell} font-normal`}>
                      {w.label}
                    </th>
                    <td className={cell}>
                      <EditableNumber field={w} label={`Stand By ${w.label}`} disabled={disabled} onSave={onSave} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <h3 className="mb-2 mt-4 text-sm font-medium">BME (คลัง)</h3>
            <div className="flex flex-wrap gap-x-6 gap-y-3">
              {[
                [data.infusion.bme_devices, "เครื่องใหม่ (เครื่อง)"],
                [data.infusion.chargers, "สายชาร์จ"],
                [data.infusion.clamps, "Clamp"],
                [data.infusion.ready, "พร้อมใช้งาน (เครื่อง)"],
              ].map(([f, caption]) => (
                <label key={(f as StandbyField).key} className="flex flex-col gap-1 text-xs">
                  {caption as string}
                  <EditableNumber field={f as StandbyField} label={caption as string} disabled={disabled} onSave={onSave} />
                </label>
              ))}
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => setShowBaseline(true)}
                className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm"
              >
                ตั้งค่าเริ่มต้น สายชาร์จ/Clamp
              </button>
              {data.infusion.baseline.set_at === null && (
                <span className="text-xs text-amber-500">ยังไม่ได้ตั้งค่าเริ่มต้น ระบบจึงยังคำนวณสายชาร์จ/Clamp ไม่ได้</span>
              )}
            </div>
            {showBaseline && <BaselineDialog summary={data} onClose={() => setShowBaseline(false)} />}
          </section>

          <section className="surface rounded-xl border p-4" aria-labelledby="pneumatic-title">
            <h2 id="pneumatic-title" className="mb-3 text-sm font-medium">
              Pneumatic PUMP
            </h2>
            <div className="flex flex-wrap gap-x-6 gap-y-3">
              <label className="flex flex-col gap-1 text-xs">
                เครื่องที่ใช้งานอยู่
                <EditableNumber field={data.pneumatic.in_use} disabled={disabled} onSave={onSave} />
              </label>
              <label className="flex flex-col gap-1 text-xs">
                รับคืนเครื่องวันนี้
                <EditableNumber field={data.pneumatic.returned} disabled={disabled} onSave={onSave} />
              </label>
            </div>
          </section>

          <ul className="list-disc pl-5 text-xs text-[var(--text-muted)]">
            {data.approximations.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </>
      )}

      <section className="surface rounded-xl border p-4" aria-labelledby="text-title">
        <h2 id="text-title" className="mb-2 text-sm font-medium">
          ข้อความสำหรับส่ง LINE
        </h2>
        <pre
          data-testid="standby-text"
          className="mb-3 whitespace-pre-wrap rounded-lg border border-[var(--border)] p-3 text-sm"
        >
          {text.data ?? (text.isLoading ? "กำลังโหลด..." : "")}
        </pre>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => void copy()}
            disabled={text.data === undefined}
            className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium disabled:opacity-50"
          >
            คัดลอกข้อความ
          </button>
          <button
            type="button"
            onClick={() => void download()}
            disabled={busy || !date}
            className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium disabled:opacity-50"
          >
            ดาวน์โหลด Excel
          </button>
          {copied === "ok" && <span role="status" className="text-xs">คัดลอกแล้ว</span>}
          {copied === "fail" && (
            <span role="alert" className="text-xs text-red-600">
              คัดลอกไม่สำเร็จ กรุณาเลือกข้อความด้านบนแล้วคัดลอกเอง
            </span>
          )}
        </div>
        <p className="mt-2 text-xs text-[var(--text-muted)]">
          Excel คือรายงานประจำวันของวันที่เลือก คอลัมน์ Stand By ใช้ค่าของรอบสรุป Day (20:00)
        </p>
        {downloadError && (
          <p role="alert" className="mt-2 text-xs text-red-600">
            {downloadError}
          </p>
        )}
      </section>
    </section>
  );
}
