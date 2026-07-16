import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { QRScanner } from "@/components/QRScanner";
import { apiErrorMessage } from "@/services/api";
import { createReturn, listActiveBorrows } from "@/services/borrow";
import { getEquipmentByQr } from "@/services/equipment";
import type { TransactionOut } from "@/types";

const CONDITIONS: { value: string; label: string }[] = [
  { value: "available", label: "พร้อมใช้งาน" },
  { value: "cleaning", label: "ต้องทำความสะอาด" },
  { value: "pm", label: "ต้อง PM" },
  { value: "calibration", label: "ต้องสอบเทียบ" },
  { value: "repair", label: "ต้องซ่อม" },
];

export function ReturnPage() {
  const [searchParams] = useSearchParams();
  const presetEquipmentId = searchParams.get("equipment_id");

  const [scanning, setScanning] = useState(!presetEquipmentId);
  const [transaction, setTransaction] = useState<TransactionOut | null>(null);
  const [manualQuery, setManualQuery] = useState("");
  const [condition, setCondition] = useState("available");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const findActiveTransaction = useCallback(async (equipmentId: string) => {
    const active = await listActiveBorrows();
    const match = active.find((tx) => tx.equipment.id === equipmentId);
    if (!match) {
      throw new Error("ไม่พบรายการยืมที่ยังไม่คืนสำหรับเครื่องนี้");
    }
    return match;
  }, []);

  const resolveByQr = useCallback(
    async (value: string) => {
      setError(null);
      try {
        const qr = value.startsWith("MEP:") ? value : `MEP:${value}`;
        const eq = await getEquipmentByQr(qr);
        const tx = await findActiveTransaction(eq.id);
        setTransaction(tx);
        setScanning(false);
      } catch (err) {
        setError(err instanceof Error ? err.message : apiErrorMessage(err, "ไม่พบรายการยืม"));
      }
    },
    [findActiveTransaction]
  );

  useEffect(() => {
    if (presetEquipmentId) {
      findActiveTransaction(presetEquipmentId)
        .then(setTransaction)
        .catch((err) => setError(err instanceof Error ? err.message : "ไม่พบรายการยืม"));
    }
  }, [presetEquipmentId, findActiveTransaction]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!transaction) return;
    setSubmitting(true);
    setError(null);
    try {
      await createReturn(transaction.id, { condition, notes: notes || undefined });
      setSuccess(true);
    } catch (err) {
      setError(apiErrorMessage(err, "คืนเครื่องมือไม่สำเร็จ"));
    } finally {
      setSubmitting(false);
    }
  };

  if (success) {
    return (
      <div className="surface mx-auto mt-8 max-w-sm rounded-xl border p-6 text-center">
        <div className="mb-2 text-4xl">✅</div>
        <h2 className="text-lg font-semibold">คืนเครื่องมือสำเร็จ</h2>
        <button
          onClick={() => {
            setSuccess(false);
            setTransaction(null);
            setScanning(true);
          }}
          className="mt-4 rounded-lg bg-status-available px-4 py-2 text-sm font-medium text-white"
        >
          คืนเครื่องถัดไป
        </button>
      </div>
    );
  }

  if (!transaction) {
    return (
      <div className="mx-auto flex max-w-sm flex-col gap-4">
        <h1 className="text-lg font-semibold">คืนเครื่องมือ</h1>
        <QRScanner active={scanning} onScan={resolveByQr} />
        <div className="flex gap-2">
          <input
            value={manualQuery}
            onChange={(e) => setManualQuery(e.target.value)}
            placeholder="หรือกรอกเลขครุภัณฑ์"
            className="flex-1 rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
          />
          <button
            onClick={() => manualQuery && resolveByQr(manualQuery)}
            className="rounded-lg bg-status-available px-4 py-2 text-sm font-medium text-white"
          >
            ค้นหา
          </button>
        </div>
        {error && <p className="text-sm text-status-repair">{error}</p>}
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="mx-auto flex max-w-sm flex-col gap-4">
      <div className="surface rounded-xl border p-4">
        <div className="font-medium">{transaction.equipment.equipment_name}</div>
        <div className="text-sm text-[var(--text-muted)]">{transaction.equipment.asset_number}</div>
        <div className="mt-1 text-sm text-[var(--text-muted)]">
          ผู้ยืม: {transaction.borrower_name} · ยืมเมื่อ {new Date(transaction.borrowed_at).toLocaleString("th-TH")}
        </div>
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium">สภาพเครื่องเมื่อคืน</label>
        <div className="grid grid-cols-2 gap-2">
          {CONDITIONS.map((c) => (
            <label
              key={c.value}
              className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
                condition === c.value ? "border-status-available bg-status-available/10" : "border-[var(--border)]"
              }`}
            >
              <input
                type="radio"
                name="condition"
                value={c.value}
                checked={condition === c.value}
                onChange={() => setCondition(c.value)}
              />
              {c.label}
            </label>
          ))}
        </div>
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium">หมายเหตุ</label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
          rows={2}
        />
      </div>

      {error && <p className="text-sm text-status-repair">{error}</p>}

      <button
        type="submit"
        disabled={submitting}
        className="rounded-lg bg-status-available py-2.5 font-medium text-white disabled:opacity-60"
      >
        {submitting ? "กำลังบันทึก..." : "ยืนยันการคืน"}
      </button>
    </form>
  );
}
