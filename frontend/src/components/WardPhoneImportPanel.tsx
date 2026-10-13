import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiErrorMessage } from "@/services/api";
import { importWardPhones } from "@/services/masterData";
import type { WardPhoneImportResponse, WardPhoneImportRow, WardPhoneImportStatus } from "@/types";
import { MAX_PHONE_IMPORT_ROWS, parseWardPhoneCsv } from "@/utils/wardPhoneCsv";

export const WARD_PHONE_STATUS_LABELS: Record<WardPhoneImportStatus, string> = {
  will_set: "จะตั้งเบอร์ใหม่",
  will_overwrite: "จะเขียนทับเบอร์เดิม",
  skipped_existing: "ข้าม (มีเบอร์อยู่แล้ว)",
  unchanged: "ไม่เปลี่ยนแปลง",
  unknown_ward: "ไม่พบหอผู้ป่วย",
  invalid_phone: "เบอร์โทรไม่ถูกต้อง",
  duplicate_ward_name: "ชื่อหอผู้ป่วยซ้ำในไฟล์",
  ambiguous_ward: "ชื่อหอผู้ป่วยกำกวม",
};

// Roadmap PR25E slice S0: one-time ward phone import (administrator only,
// shown only to admins by the caller; the backend enforces it).
export function WardPhoneImportPanel() {
  const [text, setText] = useState("");
  const [rows, setRows] = useState<WardPhoneImportRow[] | null>(null);
  const [overwrite, setOverwrite] = useState(false);
  const [result, setResult] = useState<WardPhoneImportResponse | null>(null);
  const [applied, setApplied] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const invalidate = () => {
    setResult(null);
    setApplied(false);
  };

  const handleFile = async (file: File | undefined) => {
    if (!file) return;
    // TextDecoder-free: File.text() decodes UTF-8; BOM is stripped by the parser.
    setText(await file.text());
    invalidate();
  };

  const run = async (dryRun: boolean) => {
    setError(null);
    let toSend = rows;
    if (dryRun) {
      const parsed = parseWardPhoneCsv(text);
      if (parsed.error) {
        setError(parsed.error);
        setRows(null);
        invalidate();
        return;
      }
      toSend = parsed.rows;
      setRows(parsed.rows);
    }
    if (!toSend) return;
    setLoading(true);
    try {
      const res = await importWardPhones(toSend, { dryRun, overwrite });
      setResult(res);
      if (!dryRun) {
        setApplied(true);
        queryClient.invalidateQueries({ queryKey: ["wards"] });
      }
    } catch (err) {
      setError(apiErrorMessage(err, "นำเข้าเบอร์โทรไม่สำเร็จ"));
    } finally {
      setLoading(false);
    }
  };

  const changeCount =
    (result?.counts.will_set ?? 0) + (result?.counts.will_overwrite ?? 0);

  return (
    <div className="surface flex max-w-2xl flex-col gap-3 rounded-xl border p-4">
      <p className="text-sm text-[var(--text-muted)]">
        วางหรืออัปโหลด CSV ที่มีคอลัมน์ ward_name,phone (สูงสุด {MAX_PHONE_IMPORT_ROWS} แถว;
        คอลัมน์อื่น เช่น nsmart_department จะถูกข้าม)
      </p>
      <input
        type="file"
        accept=".csv,text/csv"
        aria-label="อัปโหลดไฟล์ CSV"
        onChange={(e) => void handleFile(e.target.files?.[0])}
      />
      <textarea
        aria-label="ข้อมูล CSV"
        rows={6}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          invalidate();
        }}
        className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 font-mono text-xs"
      />
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={overwrite}
          onChange={(e) => {
            setOverwrite(e.target.checked);
            invalidate();
          }}
        />
        เขียนทับเบอร์โทรที่มีอยู่แล้ว
      </label>
      <button
        type="button"
        disabled={loading || !text.trim()}
        onClick={() => void run(true)}
        className="w-fit rounded-lg bg-status-borrowed px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
      >
        ตรวจสอบก่อนนำเข้า (Dry-run)
      </button>

      {error && <p className="text-sm text-status-repair">{error}</p>}

      {result && (
        <>
          {applied && <p className="text-sm font-medium text-status-available">นำเข้าเบอร์โทรสำเร็จ</p>}
          <table className="w-full text-left text-sm">
            <thead>
              <tr>
                <th className="py-1">หอผู้ป่วย</th>
                <th className="py-1">เบอร์โทร</th>
                <th className="py-1">ผลลัพธ์</th>
              </tr>
            </thead>
            <tbody>
              {result.results.map((r, i) => (
                <tr key={i} className="border-t">
                  <td className="py-1">{r.ward_name}</td>
                  <td className="py-1">{r.phone}</td>
                  <td className="py-1">{WARD_PHONE_STATUS_LABELS[r.status] ?? r.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!applied && (
            <button
              type="button"
              disabled={loading || changeCount === 0}
              onClick={() => void run(false)}
              className="w-fit rounded-lg bg-status-available px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
            >
              ยืนยันนำเข้า ({changeCount} หอผู้ป่วย)
            </button>
          )}
        </>
      )}
    </div>
  );
}
