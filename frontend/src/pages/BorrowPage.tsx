import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { BcmSearchInput } from "@/components/BcmSearchInput";
import { OfflineStaleGate } from "@/components/OfflineStaleGate";
import { QRScanner } from "@/components/QRScanner";
import { StatusBadge } from "@/components/StatusBadge";
import { useDirtyForm } from "@/hooks/useDirtyForm";
import { useOfflineMode } from "@/hooks/useOfflineMode";
import {
  effectiveCachedEquipment,
  enqueueOfflineDispatch,
  LocalOpError,
  searchCachedBcm,
} from "@/offline/localOps";
import { listRefs, OfflineStoreError } from "@/offline/offlineStore";
import { apiErrorMessage } from "@/services/api";
import { createBorrow } from "@/services/borrow";
import { getEquipment, resolveEquipmentByQr } from "@/services/equipment";
import { listDepartments, listWards } from "@/services/masterData";
import { useUiStore } from "@/store/uiStore";
import { resolveWardPhone } from "@/utils/wardPhone";
import type { BcmSuggestion, Department, DispatchType, Equipment, RoutineRound, Ward } from "@/types";

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
  // PR25E S4: set after an offline save; never shown as "recorded" (design 14).
  const [pendingSync, setPendingSync] = useState(false);
  const offline = useOfflineMode();
  const [submitting, setSubmitting] = useState(false);

  const lastWard = useUiStore((s) => s.lastWard);
  const setLastWard = useUiStore((s) => s.setLastWard);

  const [wardId, setWardId] = useState(lastWard ?? "");
  const [dispatchType, setDispatchType] = useState<DispatchType>("on_demand");
  const [routineRound, setRoutineRound] = useState<RoutineRound | "">("");
  const [phone, setPhone] = useState("");
  const [notes, setNotes] = useState("");
  useDirtyForm(equipment !== null && !success && !pendingSync);

  const { data: onlineWards } = useQuery({ queryKey: ["wards"], queryFn: listWards });
  const { data: onlineDepartments } = useQuery({ queryKey: ["departments"], queryFn: listDepartments });

  // Offline: wards/departments (with phones) come from the IndexedDB snapshot.
  const [cachedRefs, setCachedRefs] = useState<{ wards: Ward[]; departments: Department[] } | null>(null);
  useEffect(() => {
    if (!offline) return;
    let live = true;
    void Promise.all([listRefs("ref_wards"), listRefs("ref_departments")])
      .then(([w, d]) => live && setCachedRefs({ wards: w as unknown as Ward[], departments: d as unknown as Department[] }))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [offline]);
  const wards = offline && cachedRefs ? cachedRefs.wards : onlineWards;
  const departments = offline && cachedRefs ? cachedRefs.departments : onlineDepartments;

  // Roadmap PR25E S0: prefill phone from the selected ward (department
  // fallback) until the operator types their own value.
  const phoneTouched = useRef(false);
  useEffect(() => {
    if (phoneTouched.current || !wardId) return;
    const ward = (wards ?? []).find((w) => w.id === wardId);
    setPhone(resolveWardPhone(ward, departments));
  }, [wardId, wards, departments]);

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
  const handleBcmSelect = useCallback(
    async (suggestion: BcmSuggestion) => {
    setError(null);
    try {
      if (offline) {
        const { equipment: cached } = await effectiveCachedEquipment(suggestion.id);
        setEquipment(cached);
        setScanning(false);
        return;
      }
      const eq = await getEquipment(suggestion.id);
      setEquipment(eq);
      setScanning(false);
    } catch (err) {
      setError(err instanceof LocalOpError ? err.message : apiErrorMessage(err, "ไม่พบเครื่องมือ"));
    }
    },
    [offline],
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!equipment || !wardId) return;
    setSubmitting(true);
    setError(null);
    if (offline) {
      try {
        await enqueueOfflineDispatch({
          equipment_id: equipment.id,
          ward_id: wardId,
          dispatch_type: dispatchType,
          routine_round: dispatchType === "routine_round" ? (routineRound as RoutineRound) : undefined,
          phone_number: phone || undefined,
          notes: notes || undefined,
        });
        setLastWard(wardId || null);
        setPendingSync(true);
      } catch (err) {
        setError(
          err instanceof LocalOpError || err instanceof OfflineStoreError ? err.message : "บันทึกในเครื่องไม่สำเร็จ",
        );
      } finally {
        setSubmitting(false);
      }
      return;
    }
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
      setError(apiErrorMessage(err, "เบิกเครื่องมือไม่สำเร็จ"));
    } finally {
      setSubmitting(false);
    }
  };

  if (pendingSync) {
    return (
      <div className="surface mx-auto mt-8 max-w-sm rounded-xl border p-6 text-center">
        <div className="mb-2 text-4xl">🕓</div>
        <h2 className="text-lg font-semibold">บันทึกในเครื่องแล้ว — ยังไม่ได้ส่งเข้าระบบ</h2>
        <p className="mt-1 text-sm text-[var(--text-muted)]">ระบบจะส่งอัตโนมัติเมื่อเชื่อมต่อเซิร์ฟเวอร์ได้</p>
        <button
          onClick={() => {
            setPendingSync(false);
            phoneTouched.current = false;
            setPhone(resolveWardPhone((wards ?? []).find((w) => w.id === wardId), departments));
            setEquipment(null);
            setScanning(true);
          }}
          className="mt-4 rounded-lg bg-status-borrowed px-4 py-2 text-sm font-medium text-white"
        >
          เบิกเครื่องถัดไป
        </button>
      </div>
    );
  }

  if (success) {
    return (
      <div className="surface mx-auto mt-8 max-w-sm rounded-xl border p-6 text-center">
        <div className="mb-2 text-4xl">✅</div>
        <h2 className="text-lg font-semibold">เบิกสำเร็จ</h2>
        <p className="mt-1 text-sm text-[var(--text-muted)]">เลขที่รายการ {success}</p>
        <button
          onClick={() => {
            setSuccess(null);
            phoneTouched.current = false;
            setPhone(resolveWardPhone((wards ?? []).find((w) => w.id === wardId), departments));
            setEquipment(null);
            setScanning(true);
          }}
          className="mt-4 rounded-lg bg-status-borrowed px-4 py-2 text-sm font-medium text-white"
        >
          เบิกเครื่องถัดไป
        </button>
      </div>
    );
  }

  if (!equipment) {
    return (
      <div className="mx-auto flex max-w-sm flex-col gap-4">
        {offline && <OfflineStaleGate />}
        <h1 className="text-lg font-semibold">เบิกเครื่องมือ</h1>
        {offline ? (
          <p className="text-sm text-[var(--text-muted)]">
            เซิร์ฟเวอร์ไม่พร้อมใช้งาน — ค้นหาด้วยรหัส BCM จากข้อมูลในเครื่อง (สแกน QR ใช้ได้เฉพาะตอนออนไลน์)
          </p>
        ) : (
          <>
            <QRScanner active={scanning} onScan={resolveEquipmentFromQr} />
            <p className="text-center text-sm text-[var(--text-muted)]">หรือค้นหาด้วยรหัส BCM</p>
          </>
        )}
        <BcmSearchInput onSelect={handleBcmSelect} search={offline ? searchCachedBcm : undefined} />
        {error && <p className="text-sm text-status-repair">{error}</p>}
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="mx-auto flex max-w-sm flex-col gap-4">
      {offline && <OfflineStaleGate />}
      <div className="surface rounded-xl border p-4">
        <div className="font-medium">{equipment.equipment_name}</div>
        <div className="text-sm text-[var(--text-muted)]">{equipment.asset_number || equipment.bcm_code}</div>
        <div className="mt-2">
          <StatusBadge status={equipment.status} />
        </div>
      </div>

      {equipment.status !== "available_at_pool" ? (
        <p className="rounded-lg bg-status-repair/10 p-3 text-sm text-status-repair">
          เครื่องนี้ไม่พร้อมให้เบิก (สถานะปัจจุบัน: {equipment.status})
        </p>
      ) : (
        <>
          <div>
            <label htmlFor="borrow-ward" className="mb-1 block text-sm font-medium">
              หอผู้ป่วยที่รับเครื่อง (บันทึก ณ วันที่เบิก) *
            </label>
            <select
              id="borrow-ward"
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
            {/* Workflow Audit §7.1: the ward field must never imply
                real-time location tracking -- this is a one-time record of
                where the equipment was first sent, not a live location. */}
            <p className="mt-1 text-xs text-[var(--text-muted)]">
              ระบบบันทึกเฉพาะหอผู้ป่วยที่ส่งเครื่องไปครั้งแรก ไม่ได้ติดตามการเคลื่อนย้ายเครื่องมือในภายหลัง
            </p>
          </div>
          <div>
            <label htmlFor="borrow-dispatch-type" className="mb-1 block text-sm font-medium">
              ประเภทการเบิก *
            </label>
            <select
              id="borrow-dispatch-type"
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
              <label htmlFor="borrow-routine-round" className="mb-1 block text-sm font-medium">
                รอบเวลา *
              </label>
              <select
                id="borrow-routine-round"
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
            <label htmlFor="borrow-phone" className="mb-1 block text-sm font-medium">
              เบอร์โทร
            </label>
            <input
              id="borrow-phone"
              value={phone}
              onChange={(e) => {
                phoneTouched.current = true;
                setPhone(e.target.value);
              }}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
            />
          </div>
          <div>
            <label htmlFor="borrow-notes" className="mb-1 block text-sm font-medium">
              หมายเหตุ
            </label>
            <textarea
              id="borrow-notes"
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
            {submitting ? "กำลังบันทึก..." : offline ? "บันทึกการเบิก (ในเครื่อง)" : "ยืนยันการเบิก"}
          </button>
        </>
      )}
    </form>
  );
}
