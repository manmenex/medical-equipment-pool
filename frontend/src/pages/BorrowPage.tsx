import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { BcmSearchInput } from "@/components/BcmSearchInput";
import { QRScanner } from "@/components/QRScanner";
import { StatusBadge } from "@/components/StatusBadge";
import { apiErrorMessage } from "@/services/api";
import { createBorrow } from "@/services/borrow";
import { getEquipment, resolveEquipmentByQr } from "@/services/equipment";
import { listWards } from "@/services/masterData";
import { useUiStore } from "@/store/uiStore";
import type { BcmSuggestion, DispatchType, Equipment, RoutineRound } from "@/types";

// Roadmap PR7b confirmed fixed four-round MVP schedule (docs/audits/
// 04-consolidated-implementation-plan.md's confirmed-requirements table) --
// no named label for any round is confirmed anywhere, so none is invented
// here; the option value/label is the literal clock time itself.
const ROUTINE_ROUNDS: RoutineRound[] = ["06:00", "11:00", "15:00", "21:00"];

export function BorrowPage() {
  const [searchParams] = useSearchParams();
  const presetEquipmentId = searchParams.get("equipment_id");

  const [scanning, setScanning] = useState(!presetEquipmentId);
  const [equipment, setEquipment] = useState<Equipment | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const lastWard = useUiStore((s) => s.lastWard);
  const setLastWard = useUiStore((s) => s.setLastWard);

  const [wardId, setWardId] = useState(lastWard ?? "");
  const [dispatchType, setDispatchType] = useState<DispatchType>("on_demand");
  const [routineRound, setRoutineRound] = useState<RoutineRound | "">("");
  const [phone, setPhone] = useState("");
  const [notes, setNotes] = useState("");

  const { data: wards } = useQuery({ queryKey: ["wards"], queryFn: listWards });

  useEffect(() => {
    if (presetEquipmentId) {
      getEquipment(presetEquipmentId)
        .then(setEquipment)
        .catch(() => setError("ไม่พบเครื่องมือ"));
    }
  }, [presetEquipmentId]);

  // Roadmap PR5 primary workflow: scan existing QR -> extract Item No
  // (server-side) -> Equipment Master lookup.
  const resolveEquipmentFromQr = useCallback(async (rawValue: string) => {
    setError(null);
    try {
      const eq = await resolveEquipmentByQr(rawValue);
      setEquipment(eq);
      setScanning(false);
    } catch (err) {
      setError(apiErrorMessage(err, "ไม่พบเครื่องมือจาก QR ที่สแกน"));
    }
  }, []);

  // Roadmap PR5 fallback workflow: BCM Code search -> select a suggestion
  // -> Equipment Master lookup by id.
  const handleBcmSelect = useCallback(async (suggestion: BcmSuggestion) => {
    setError(null);
    try {
      const eq = await getEquipment(suggestion.id);
      setEquipment(eq);
      setScanning(false);
    } catch (err) {
      setError(apiErrorMessage(err, "ไม่พบเครื่องมือ"));
    }
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!equipment || !wardId) return;
    setSubmitting(true);
    setError(null);
    try {
      const tx = await createBorrow({
        equipment_id: equipment.id,
        ward_id: wardId,
        dispatch_type: dispatchType,
        routine_round: dispatchType === "routine_round" ? (routineRound as RoutineRound) : undefined,
        phone_number: phone || undefined,
        notes: notes || undefined,
      });
      setLastWard(wardId || null);
      setSuccess(tx.transaction_no);
    } catch (err) {
      setError(apiErrorMessage(err, "ยืมเครื่องมือไม่สำเร็จ"));
    } finally {
      setSubmitting(false);
    }
  };

  if (success) {
    return (
      <div className="surface mx-auto mt-8 max-w-sm rounded-xl border p-6 text-center">
        <div className="mb-2 text-4xl">✅</div>
        <h2 className="text-lg font-semibold">ยืมสำเร็จ</h2>
        <p className="mt-1 text-sm text-[var(--text-muted)]">เลขที่รายการ {success}</p>
        <button
          onClick={() => {
            setSuccess(null);
            setEquipment(null);
            setScanning(true);
          }}
          className="mt-4 rounded-lg bg-status-borrowed px-4 py-2 text-sm font-medium text-white"
        >
          ยืมเครื่องถัดไป
        </button>
      </div>
    );
  }

  if (!equipment) {
    return (
      <div className="mx-auto flex max-w-sm flex-col gap-4">
        <h1 className="text-lg font-semibold">ยืมเครื่องมือ</h1>
        <QRScanner active={scanning} onScan={resolveEquipmentFromQr} />
        <p className="text-center text-sm text-[var(--text-muted)]">หรือค้นหาด้วยรหัส BCM</p>
        <BcmSearchInput onSelect={handleBcmSelect} />
        {error && <p className="text-sm text-status-repair">{error}</p>}
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="mx-auto flex max-w-sm flex-col gap-4">
      <div className="surface rounded-xl border p-4">
        <div className="font-medium">{equipment.equipment_name}</div>
        <div className="text-sm text-[var(--text-muted)]">{equipment.asset_number}</div>
        <div className="mt-2">
          <StatusBadge status={equipment.status} />
        </div>
      </div>

      {equipment.status !== "available_at_pool" ? (
        <p className="rounded-lg bg-status-repair/10 p-3 text-sm text-status-repair">
          เครื่องนี้ไม่พร้อมให้ยืม (สถานะปัจจุบัน: {equipment.status})
        </p>
      ) : (
        <>
          <div>
            <label className="mb-1 block text-sm font-medium">หอผู้ป่วย / Ward *</label>
            <select
              required
              value={wardId}
              onChange={(e) => setWardId(e.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
            >
              <option value="">- เลือก -</option>
              {(wards ?? []).map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">ประเภทการเบิก *</label>
            <select
              required
              value={dispatchType}
              onChange={(e) => {
                const next = e.target.value as DispatchType;
                setDispatchType(next);
                if (next === "on_demand") setRoutineRound("");
              }}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
            >
              <option value="on_demand">เบิกตามคำขอ (On-Demand)</option>
              <option value="routine_round">รอบเวลาปกติ (Routine Round)</option>
            </select>
          </div>
          {dispatchType === "routine_round" && (
            <div>
              <label className="mb-1 block text-sm font-medium">รอบเวลา *</label>
              <select
                required
                value={routineRound}
                onChange={(e) => setRoutineRound(e.target.value as RoutineRound)}
                className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
              >
                <option value="">- เลือก -</option>
                {ROUTINE_ROUNDS.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div>
            <label className="mb-1 block text-sm font-medium">เบอร์โทร</label>
            <input
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
            />
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
            disabled={submitting || !wardId || (dispatchType === "routine_round" && !routineRound)}
            className="rounded-lg bg-status-borrowed py-2.5 font-medium text-white disabled:opacity-60"
          >
            {submitting ? "กำลังบันทึก..." : "ยืนยันการยืม"}
          </button>
        </>
      )}
    </form>
  );
}
