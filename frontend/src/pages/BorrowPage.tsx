import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { CheckGlyphs, ItemEditPanel } from "@/components/entry/ItemEditPanel";
import { ChecksEditor } from "@/components/entry/ChecksEditor";
import { resolveBcmText } from "@/components/entry/lookup";
import { ScanBar } from "@/components/entry/ScanBar";
import { useWardRefs } from "@/components/entry/useWardRefs";
import { WardSection } from "@/components/entry/WardSection";
import { OfflineStaleGate } from "@/components/OfflineStaleGate";
import { useDirtyForm } from "@/hooks/useDirtyForm";
import { useOfflineMode } from "@/hooks/useOfflineMode";
import { cachedChecklistKind, effectiveCachedEquipment, enqueueOfflineDispatch, LocalOpError } from "@/offline/localOps";
import { OfflineStoreError } from "@/offline/offlineStore";
import { apiErrorMessage } from "@/services/api";
import { dispatchBatch, type DispatchBatchItem } from "@/services/borrow";
import { batchErrorText, defaultChecks } from "@/services/checks";
import { getDispatchCheck, getEquipment, resolveEquipmentByQr, type DispatchCheck } from "@/services/equipment";
import { useUiStore } from "@/store/uiStore";
import type { Checks, ChecklistKind, Equipment } from "@/types";

// Roadmap PR27/PR28 (D3/D4/D7/D10): ward-first multi-equipment dispatch. One
// ward + N scanned items; each item carries its own accessory/Cryo-Cuff check
// and is submitted through dispatch-batch (online) or queued as N single sync
// operations (offline). Roadmap PR31 (D8): status warnings are confirmed by the
// operator pressing the big confirm button (acknowledge + expected_* sent).
export interface DispatchItem {
  equipmentId: string;
  bcm: string;
  name: string;
  /** null while offline: dispatch-check is unavailable, so no status/kind is known. */
  check: DispatchCheck | null;
  kind: ChecklistKind;
  checks: Checks;
  error?: string;
}

const isWarning = (c: DispatchCheck | null) => !!c && (c.warning === "already_dispatched" || c.warning === "defective");

function rowSummary(it: DispatchItem) {
  const c = it.check;
  if (c?.warning === "already_dispatched") {
    return <span className="whitespace-nowrap text-xs font-medium text-amber-400">⚠ ค้าง {c.current_ward_name ?? "-"}</span>;
  }
  if (c?.warning === "defective") {
    return <span className="whitespace-nowrap text-xs font-medium text-amber-400">⚠ เสีย</span>;
  }
  return <CheckGlyphs checks={it.checks} />;
}

export function BorrowPage() {
  const [searchParams] = useSearchParams();
  const presetEquipmentId = searchParams.get("equipment_id");
  const offline = useOfflineMode();
  const { wards, departments } = useWardRefs(offline);
  const bumpWardUsage = useUiStore((s) => s.bumpWardUsage);
  const setLastWard = useUiStore((s) => s.setLastWard);

  const [wardId, setWardId] = useState("");
  const [contact, setContact] = useState("");
  const [phone, setPhone] = useState("");
  const [note, setNote] = useState("");
  const [items, setItems] = useState<DispatchItem[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [done, setDone] = useState<{ bcm: string; ref: string }[]>([]);
  const [queuedCount, setQueuedCount] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [adding, setAdding] = useState(false);
  const submittingRef = useRef(false);
  const itemsRef = useRef<DispatchItem[]>([]);
  itemsRef.current = items;
  useDirtyForm(items.length > 0);

  const addEquipment = useCallback(
    async (eq: Pick<Equipment, "id" | "bcm_code" | "equipment_name" | "status" | "asset_number">) => {
      const label = eq.bcm_code ?? eq.asset_number ?? eq.equipment_name;
      if (itemsRef.current.some((i) => i.equipmentId === eq.id)) return; // duplicates ignored
      let check: DispatchCheck | null = null;
      if (!offline) {
        check = await getDispatchCheck(eq.id);
        if (check.warning === "decommissioned" || !check.dispatchable) {
          setNotice(`⛔ ${label} ปลดระวางแล้ว ไม่ถูกเพิ่ม`);
          return;
        }
      } else if (eq.status === "decommissioned") {
        setNotice(`⛔ ${label} ปลดระวางแล้ว ไม่ถูกเพิ่ม`);
        return;
      }
      const kind: ChecklistKind = check?.checklist_kind ?? (offline ? await cachedChecklistKind(eq.id) : "standard");
      setNotice(null);
      setDone([]);
      setItems((prev) =>
        prev.some((i) => i.equipmentId === eq.id)
          ? prev
          : [...prev, { equipmentId: eq.id, bcm: label, name: eq.equipment_name, check, kind, checks: defaultChecks(kind) }],
      );
    },
    [offline],
  );

  const addById = useCallback(
    async (id: string) => {
      setAdding(true);
      try {
        const eq = offline ? (await effectiveCachedEquipment(id)).equipment : await getEquipment(id);
        await addEquipment(eq);
      } catch (err) {
        setNotice(`⛔ ${err instanceof LocalOpError ? err.message : apiErrorMessage(err, "ไม่พบเครื่องมือ")} ไม่ถูกเพิ่ม`);
      } finally {
        setAdding(false);
      }
    },
    [offline, addEquipment],
  );

  const addByBcm = useCallback(
    async (text: string) => {
      setAdding(true);
      try {
        const s = await resolveBcmText(text, offline);
        if (!s) {
          setNotice(`⛔ ไม่พบเครื่อง ${text} ไม่ถูกเพิ่ม`);
          return;
        }
        const eq = offline ? (await effectiveCachedEquipment(s.id)).equipment : await getEquipment(s.id);
        await addEquipment(eq);
      } catch (err) {
        setNotice(`⛔ ${err instanceof LocalOpError ? err.message : apiErrorMessage(err, `ไม่พบเครื่อง ${text}`)} ไม่ถูกเพิ่ม`);
      } finally {
        setAdding(false);
      }
    },
    [offline, addEquipment],
  );

  const addByQr = useCallback(
    async (raw: string) => {
      try {
        const eq = await resolveEquipmentByQr(raw);
        await addEquipment(eq);
      } catch (err) {
        setNotice(`⛔ ${apiErrorMessage(err, "ไม่พบเครื่องมือจาก QR ที่สแกน")} ไม่ถูกเพิ่ม`);
      }
    },
    [addEquipment],
  );

  useEffect(() => {
    if (presetEquipmentId) void addById(presetEquipmentId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [presetEquipmentId]);

  const patch = (id: string, p: Partial<DispatchItem>) =>
    setItems((prev) => prev.map((i) => (i.equipmentId === id ? { ...i, ...p } : i)));
  const remove = (id: string) => {
    setItems((prev) => prev.filter((i) => i.equipmentId !== id));
    setEditing(null);
  };

  const submit = async () => {
    if (!wardId || items.length === 0 || submittingRef.current) return;
    submittingRef.current = true;
    setSubmitting(true);
    setNotice(null);
    const sent = items;
    try {
      if (offline) {
        // Offline: N single sync operations, sharing the contact name (docs/api/ward-first-entry.md s6).
        const failed: DispatchItem[] = [];
        let queued = 0;
        for (const it of sent) {
          try {
            await enqueueOfflineDispatch({
              equipment_id: it.equipmentId,
              ward_id: wardId,
              phone_number: phone || undefined,
              notes: note || undefined,
              ward_contact_name: contact.trim() || undefined,
              dispatch_checks: it.checks,
            });
            queued += 1;
          } catch (err) {
            const msg = err instanceof LocalOpError || err instanceof OfflineStoreError ? err.message : "บันทึกในเครื่องไม่สำเร็จ";
            failed.push({ ...it, error: msg });
          }
        }
        setItems(failed);
        setQueuedCount((n) => n + queued);
        if (queued > 0) {
          setLastWard(wardId);
          bumpWardUsage(wardId);
        }
        return;
      }

      const payloadItems: DispatchBatchItem[] = sent.map((it) => {
        const base: DispatchBatchItem = { equipment_id: it.equipmentId, checks: it.checks };
        if (isWarning(it.check)) {
          return {
            ...base,
            acknowledge_status_warning: true,
            expected_open_transaction_id: it.check?.open_transaction_id ?? null,
            expected_status: it.check?.status ?? null,
          };
        }
        return base;
      });
      const resp = await dispatchBatch({
        ward_id: wardId,
        ward_contact_name: contact.trim() || null,
        phone: phone.trim() || null,
        note: note.trim() || null,
        items: payloadItems,
      });
      const ok: { bcm: string; ref: string }[] = [];
      const keep: DispatchItem[] = [];
      const refresh: string[] = [];
      for (let i = 0; i < sent.length; i++) {
        const r = resp.results.find((x) => x.index === i);
        if (r?.ok) {
          ok.push({ bcm: sent[i].bcm, ref: r.transaction_no ?? "" });
        } else {
          keep.push({ ...sent[i], error: batchErrorText(r?.error?.code, r?.error?.message) });
          const code = r?.error?.code;
          if (code === "DISPATCH_STATUS_WARNING" || code === "DISPATCH_WARNING_STALE" || code === "EQUIPMENT_STATUS_CHANGED") {
            refresh.push(sent[i].equipmentId);
          }
        }
      }
      if (ok.length > 0) {
        setLastWard(wardId);
        bumpWardUsage(wardId);
        setNote("");
      }
      setDone(ok);
      setItems(keep);
      // A status that changed since the scan needs a fresh check before the retry.
      await Promise.all(
        refresh.map(async (id) => {
          try {
            const fresh = await getDispatchCheck(id);
            if (fresh.warning === "decommissioned" || !fresh.dispatchable) {
              const gone = keep.find((k) => k.equipmentId === id);
              setItems((prev) => prev.filter((i) => i.equipmentId !== id));
              setNotice(`⛔ ${gone?.bcm ?? ""} ปลดระวางแล้ว ไม่ถูกเพิ่ม`);
            } else {
              patch(id, { check: fresh });
            }
          } catch {
            /* keep the old check; the operator can remove and re-scan */
          }
        }),
      );
    } catch (err) {
      setNotice(apiErrorMessage(err, "เบิกเครื่องมือไม่สำเร็จ"));
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  const editingItem = items.find((i) => i.equipmentId === editing) ?? null;

  return (
    <div className="mx-auto flex max-w-md flex-col gap-3 pb-6">
      {offline && <OfflineStaleGate />}
      <h1 className="text-lg font-semibold">เบิกเครื่องมือ</h1>

      <WardSection
        title="หอผู้ป่วย"
        contactLabel="ชื่อผู้รับ (Ward)"
        wards={wards}
        departments={departments}
        wardId={wardId}
        onWardChange={setWardId}
        contact={contact}
        onContact={setContact}
        phone={phone}
        onPhone={setPhone}
      />

      <section className="surface rounded-xl border p-3" aria-label="สแกนเครื่อง">
        <h2 className="mb-2 text-sm font-semibold">สแกนเครื่อง ({items.length} เครื่อง)</h2>
        <ScanBar onBcm={(t) => void addByBcm(t)} onQr={(r) => void addByQr(r)} busy={adding} offline={offline} />
        {notice && (
          <p role="alert" className="mt-2 rounded-lg bg-status-repair/10 px-3 py-2 text-sm text-status-repair">
            {notice}
          </p>
        )}
        <ul className="mt-2 flex flex-col gap-1.5">
          {items.map((it) => {
            const open = editing === it.equipmentId;
            const warn = isWarning(it.check);
            return (
              <li key={it.equipmentId} className="flex flex-col gap-1">
                {!open && (
                  <button
                    type="button"
                    aria-label={`แก้ไข ${it.bcm}`}
                    onClick={() => setEditing(it.equipmentId)}
                    className={`flex min-h-11 w-full items-center gap-2 rounded-lg border px-3 py-2 text-left ${
                      warn ? "border-amber-500/60 bg-amber-500/10" : "border-[var(--border)]"
                    }`}
                  >
                    <strong className="text-sm">{it.bcm}</strong>
                    <span className="min-w-0 flex-1 truncate text-xs text-[var(--text-muted)]">{it.name}</span>
                    {rowSummary(it)}
                    <span aria-hidden="true">›</span>
                  </button>
                )}
                {open && editingItem && (
                  <ItemEditPanel
                    bcm={it.bcm}
                    name={it.name}
                    statusLine={
                      <>
                        {it.kind === "cryo_cuff" ? "Cryo-Cuff" : "ตรวจสภาพอุปกรณ์"}
                        {it.check?.warning === "already_dispatched" && (
                          <span className="text-amber-400">
                            {" "}
                            · ⚠ ถูกจ่ายไป {it.check.current_ward_name ?? "-"} ยังไม่บันทึกรับคืน (ยืนยันเพื่อเบิกซ้ำ ระบบจะปิดรายการเดิม)
                          </span>
                        )}
                        {it.check?.warning === "defective" && (
                          <span className="text-amber-400"> · ⚠ เครื่องนี้ถูกแจ้งเสีย (ยืนยันเพื่อเบิกต่อ)</span>
                        )}
                      </>
                    }
                    onRemove={() => remove(it.equipmentId)}
                    onDone={() => setEditing(null)}
                    // PR29: patient HN field goes into extraSlot here (not built yet).
                    extraSlot={null}
                  >
                    <ChecksEditor checks={it.checks} onChange={(c) => patch(it.equipmentId, { checks: c })} />
                  </ItemEditPanel>
                )}
                {it.error && (
                  <p role="alert" className="px-1 text-xs text-status-repair">
                    ✗ {it.bcm}: {it.error}
                  </p>
                )}
                {offline && !it.check && !open && (
                  <p className="px-1 text-xs text-[var(--text-muted)]">ตรวจสอบสถานะไม่ได้ (ออฟไลน์)</p>
                )}
              </li>
            );
          })}
        </ul>
      </section>

      <input
        aria-label="หมายเหตุ (ไม่บังคับ)"
        placeholder="หมายเหตุ (ไม่บังคับ)"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        className="h-10 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 text-sm"
      />

      {done.length > 0 && (
        <ul aria-label="ผลการเบิก" className="rounded-lg border border-status-available/40 bg-status-available/10 p-2 text-sm">
          {done.map((d) => (
            <li key={d.bcm} className="text-status-available">
              ✓ {d.bcm} {d.ref && `(${d.ref})`}
            </li>
          ))}
        </ul>
      )}
      {queuedCount > 0 && (
        <p role="status" className="rounded-lg border border-[var(--border)] p-2 text-sm">
          🕓 บันทึกในเครื่องแล้ว {queuedCount} เครื่อง — ยังไม่ได้ส่งเข้าระบบ ระบบจะส่งอัตโนมัติเมื่อเชื่อมต่อได้
        </p>
      )}

      <div className="flex flex-col items-center gap-1">
        <button
          type="button"
          onClick={() => void submit()}
          disabled={submitting || items.length === 0 || !wardId}
          className="w-full rounded-xl bg-status-borrowed py-3 text-base font-semibold text-white disabled:opacity-50"
        >
          {submitting ? "กำลังบันทึก..." : `ยืนยันการเบิก (${items.length} เครื่อง)`}
        </button>
        {!wardId && items.length > 0 && <p className="text-xs text-amber-400">กรุณาเลือกหอผู้ป่วย</p>}
        <p className="text-xs text-[var(--text-muted)]">เวลาและกะบันทึกอัตโนมัติ</p>
      </div>
    </div>
  );
}
