import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiErrorMessage } from "@/services/api";
import { registerDemoLoanBatch, type DemoLoanBatchResult, type DemoLoanShared } from "@/services/equipment";
import { listCategories } from "@/services/masterData";
import {
  MAX_BATCH_ROWS,
  makeRows,
  parseSerials,
  resultsByIndex,
  rowErrorText,
  type BatchRow,
} from "@/utils/demoLoanBatch";

// Roadmap PR33 (D14): administrator batch registration of demo/loan devices --
// shared fields + one row per serial number (paste an Excel column), a
// validate-only dry run with per-row errors, then an all-or-nothing commit.
// For demo/loan devices the serial number is stored as the BCM Code.
const INPUT = "rounded-lg border border-[var(--border)] bg-transparent px-3 py-2";

export function DemoLoanBatchPanel() {
  const queryClient = useQueryClient();
  const { data: categories } = useQuery({ queryKey: ["categories"], queryFn: listCategories });

  const [source, setSource] = useState<"demo" | "loan">("demo");
  const [categoryId, setCategoryId] = useState("");
  const [brand, setBrand] = useState("");
  const [model, setModel] = useState("");
  const [ownerCompany, setOwnerCompany] = useState("");
  const [dueBack, setDueBack] = useState("");
  const [pasted, setPasted] = useState("");
  const [rows, setRows] = useState<BatchRow[]>([]);
  const [result, setResult] = useState<DemoLoanBatchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const invalidateResult = () => {
    setResult(null);
    setMessage(null);
  };

  const addPasted = () => {
    const serials = parseSerials(pasted);
    if (serials.length === 0) return;
    if (rows.length + serials.length > MAX_BATCH_ROWS) {
      setError(`เพิ่มได้ไม่เกิน ${MAX_BATCH_ROWS} เครื่องต่อชุด`);
      return;
    }
    setError(null);
    setRows((prev) => [...prev, ...makeRows(serials)]);
    setPasted("");
    invalidateResult();
  };

  const patchRow = (key: number, patch: Partial<BatchRow>) => {
    setRows((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)));
    invalidateResult();
  };

  const removeRow = (key: number) => {
    setRows((prev) => prev.filter((r) => r.key !== key));
    invalidateResult();
  };

  const shared = (): DemoLoanShared => ({
    category_id: categoryId,
    brand: brand.trim() || undefined,
    model: model.trim() || undefined,
    equipment_source: source,
    owner_company: ownerCompany.trim(),
    due_back_date: dueBack || undefined,
  });

  const ready = rows.length > 0 && categoryId !== "" && ownerCompany.trim() !== "";

  const run = async (dryRun: boolean) => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const out = await registerDemoLoanBatch({
        shared: shared(),
        items: rows.map((r) => ({ serial_number: r.serial, has_charger: r.has_charger, has_clamp: r.has_clamp })),
        dry_run: dryRun,
      });
      setResult(out);
      if (out.committed) {
        setMessage(`บันทึกสำเร็จ ${out.created_count} เครื่อง`);
        setRows([]);
        setResult(null);
        void queryClient.invalidateQueries({ queryKey: ["equipment"] });
        void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      } else if (out.valid) {
        setMessage(`ตรวจสอบผ่านทั้ง ${out.total} แถว — กด "บันทึกทั้งชุด" เพื่อบันทึก`);
      }
    } catch (err) {
      setError(apiErrorMessage(err, "บันทึกไม่สำเร็จ"));
    } finally {
      setBusy(false);
    }
  };

  const byIndex = resultsByIndex(result?.rows);
  const errorRows = result ? result.rows.filter((r) => r.errors.length > 0).length : 0;

  return (
    <section className="surface flex flex-col gap-4 rounded-xl border p-4" aria-label="เพิ่มเครื่อง Demo/ยืม">
      <div className="grid gap-3 md:grid-cols-2">
        <fieldset className="flex items-center gap-4 md:col-span-2">
          <legend className="sr-only">ประเภท</legend>
          <label className="flex items-center gap-1.5 text-sm">
            <input type="radio" name="source" checked={source === "demo"} onChange={() => { setSource("demo"); invalidateResult(); }} />
            Demo
          </label>
          <label className="flex items-center gap-1.5 text-sm">
            <input type="radio" name="source" checked={source === "loan"} onChange={() => { setSource("loan"); invalidateResult(); }} />
            ยืม
          </label>
        </fieldset>
        <select
          aria-label="หมวดหมู่"
          value={categoryId}
          onChange={(e) => { setCategoryId(e.target.value); invalidateResult(); }}
          className={INPUT}
        >
          <option value="">เลือกหมวดหมู่</option>
          {(categories ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <input
          aria-label="เจ้าของเครื่อง"
          placeholder="เจ้าของเครื่อง (บริษัท/โรงพยาบาลผู้ให้ยืม)"
          value={ownerCompany}
          onChange={(e) => { setOwnerCompany(e.target.value); invalidateResult(); }}
          className={INPUT}
        />
        <input aria-label="ยี่ห้อ" placeholder="ยี่ห้อ" value={brand} onChange={(e) => { setBrand(e.target.value); invalidateResult(); }} className={INPUT} />
        <input aria-label="รุ่น" placeholder="รุ่น" value={model} onChange={(e) => { setModel(e.target.value); invalidateResult(); }} className={INPUT} />
        <label className="flex flex-col gap-1 text-sm text-[var(--text-muted)]">
          กำหนดคืน (ไม่บังคับ)
          <input
            type="date"
            aria-label="กำหนดคืน"
            value={dueBack}
            onChange={(e) => { setDueBack(e.target.value); invalidateResult(); }}
            className={INPUT}
          />
        </label>
      </div>

      <div className="flex flex-col gap-2">
        <textarea
          aria-label="วาง Serial Number"
          placeholder="วาง Serial Number บรรทัดละ 1 เครื่อง (หรือวางคอลัมน์จาก Excel)"
          rows={4}
          value={pasted}
          onChange={(e) => setPasted(e.target.value)}
          className={INPUT}
        />
        <button
          type="button"
          onClick={addPasted}
          disabled={parseSerials(pasted).length === 0}
          className="self-start rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium disabled:opacity-50"
        >
          เพิ่มลงตาราง ({parseSerials(pasted).length})
        </button>
      </div>

      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm" aria-label="รายการเครื่อง">
            <thead>
              <tr className="text-left text-[var(--text-muted)]">
                <th className="py-1 pr-2">#</th>
                <th className="py-1 pr-2">Serial Number</th>
                <th className="py-1 pr-2">มีสายชาร์จ</th>
                <th className="py-1 pr-2">มี Clamp</th>
                <th className="py-1 pr-2">ผลตรวจสอบ</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const res = byIndex.get(i);
                const bad = !!res && res.errors.length > 0;
                return (
                  <tr key={r.key} className={bad ? "bg-status-repair/10" : ""}>
                    <td className="py-1 pr-2">{i + 1}</td>
                    <td className="py-1 pr-2">
                      <input
                        aria-label={`Serial แถว ${i + 1}`}
                        value={r.serial}
                        onChange={(e) => patchRow(r.key, { serial: e.target.value })}
                        className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1"
                      />
                    </td>
                    <td className="py-1 pr-2">
                      <input
                        type="checkbox"
                        aria-label={`มีสายชาร์จ แถว ${i + 1}`}
                        checked={r.has_charger}
                        onChange={(e) => patchRow(r.key, { has_charger: e.target.checked })}
                      />
                    </td>
                    <td className="py-1 pr-2">
                      <input
                        type="checkbox"
                        aria-label={`มี Clamp แถว ${i + 1}`}
                        checked={r.has_clamp}
                        onChange={(e) => patchRow(r.key, { has_clamp: e.target.checked })}
                      />
                    </td>
                    <td className="py-1 pr-2 text-xs">
                      {res && !bad && <span className="text-status-available">✓</span>}
                      {bad && (
                        <span role="alert" className="text-status-repair">
                          {res!.errors.map(rowErrorText).join(" / ")}
                        </span>
                      )}
                    </td>
                    <td className="py-1">
                      <button type="button" aria-label={`ลบแถว ${i + 1}`} onClick={() => removeRow(r.key)} className="text-xs underline">
                        ลบ
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {result && !result.valid && (
        <p role="alert" className="text-sm text-status-repair">
          พบข้อผิดพลาด {errorRows} แถว — แก้ไขแล้วตรวจสอบอีกครั้ง (ยังไม่ได้บันทึกอะไร)
        </p>
      )}
      {message && <p className="text-sm text-status-available">{message}</p>}
      {error && <p className="text-sm text-status-repair">{error}</p>}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void run(true)}
          disabled={!ready || busy}
          className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium disabled:opacity-50"
        >
          ตรวจสอบ (dry run)
        </button>
        <button
          type="button"
          onClick={() => void run(false)}
          disabled={!ready || busy}
          className="rounded-lg bg-status-borrowed px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          บันทึกทั้งชุด ({rows.length})
        </button>
      </div>
    </section>
  );
}
