import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { CuffsOutstandingPanel } from "@/components/CuffsOutstandingPanel";
import { ChecksEditor } from "@/components/entry/ChecksEditor";
import { CheckGlyphs, ItemEditPanel } from "@/components/entry/ItemEditPanel";
import { resolveBcmText } from "@/components/entry/lookup";
import { ScanBar } from "@/components/entry/ScanBar";
import { useWardRefs } from "@/components/entry/useWardRefs";
import { WardSection } from "@/components/entry/WardSection";
import { OfflineStaleGate } from "@/components/OfflineStaleGate";
import { useDirtyForm } from "@/hooks/useDirtyForm";
import { useOfflineMode } from "@/hooks/useOfflineMode";
import { effectiveCachedEquipment, enqueueOfflineReceipt, listReceiptCandidates, LocalOpError } from "@/offline/localOps";
import { OfflineStoreError } from "@/offline/offlineStore";
import { apiErrorMessage } from "@/services/api";
import { listActiveBorrows, receiptBatch, type ReceiptBatchItem } from "@/services/borrow";
import { batchErrorText, defaultChecks, hasAbnormal, totalCuffs } from "@/services/checks";
import { getDispatchCheck, getEquipment, resolveEquipmentByQr } from "@/services/equipment";
import { useUiStore } from "@/store/uiStore";
import type { Checks, ChecklistKind, Cuffs, Equipment, ReceiptOutcome, TransactionOut } from "@/types";

// Roadmap PR27/PR28 (D3/D4/D7/D10/D11): ward-first multi-equipment receipt.
// Equipment may be received from ANY ward with no warning (only the first
// dispatch ward is recorded). Each item carries receipt checks + outcome and,
// for Cryo-Cuff, the cuffs handed back (default = issued; fewer = partial).
// Roadmap PR8B/ADR-006: the outcome is the operator's explicit choice
// (usable/defective); the checks only trigger a prompt, never an auto-change.
export interface ReceiptItem {
  equipmentId: string;
  transactionId: string;
  bcm: string;
  name: string;
  kind: ChecklistKind;
  issuedCuffs: Cuffs | null;
  checks: Checks;
  outcome: ReceiptOutcome;
  wardName?: string | null;
  error?: string;
}

const OUTCOMES: { value: ReceiptOutcome; label: string; cls: string }[] = [
  { value: "usable", label: "ใช้งานได้", cls: "border-status-available bg-status-available/10" },
  { value: "defective", label: "เสีย", cls: "border-status-repair bg-status-repair/10" },
];

function cuffsOf(c: Checks): Cuffs | null {
  return c.kind === "cryo_cuff" ? c.cuffs : null;
}

export function ReturnPage() {
  const [searchParams] = useSearchParams();
  const presetEquipmentId = searchParams.get("equipment_id");
  const offline = useOfflineMode();
  const { wards, departments } = useWardRefs(offline);
  const bumpWardUsage = useUiStore((s) => s.bumpWardUsage);
  const setLastWard = useUiStore((s) => s.setLastWard);

  const queryClient = useQueryClient();
  const submittingRef = useRef(false);
  const [tab, setTab] = useState<"receive" | "cuffs">("receive");
  const [wardId, setWardId] = useState("");
  const [contact, setContact] = useState("");
  const [phone, setPhone] = useState("");
  const [note, setNote] = useState("");
  const [items, setItems] = useState<ReceiptItem[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [done, setDone] = useState<{ bcm: string; ref: string }[]>([]);
  const [queuedCount, setQueuedCount] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [adding, setAdding] = useState(false);
  const [showOpen, setShowOpen] = useState(false);
  const itemsRef = useRef<ReceiptItem[]>([]);
  itemsRef.current = items;
  useDirtyForm(items.length > 0);

  const ward = wards.find((w) => w.id === wardId);
  const { data: active } = useQuery({
    queryKey: ["active-borrows"],
    queryFn: listActiveBorrows,
    enabled: !offline && !!wardId,
  });
  const wardOpen = (active ?? []).filter((t) => t.ward_id === wardId && !itemsRef.current.some((i) => i.transactionId === t.id));

  const toItem = (
    eq: Pick<Equipment, "id" | "bcm_code" | "asset_number" | "equipment_name">,
    tx: { id: string; kind: ChecklistKind; issued: Cuffs | null; wardName?: string | null },
  ): ReceiptItem => ({
    equipmentId: eq.id,
    transactionId: tx.id,
    bcm: eq.bcm_code ?? eq.asset_number ?? eq.equipment_name,
    name: eq.equipment_name,
    kind: tx.kind,
    issuedCuffs: tx.issued,
    checks: defaultChecks(tx.kind, tx.issued ?? undefined),
    outcome: "usable",
    wardName: tx.wardName,
  });

  const addEquipment = useCallback(
    async (eq: Pick<Equipment, "id" | "bcm_code" | "asset_number" | "equipment_name">) => {
      const label = eq.bcm_code ?? eq.asset_number ?? eq.equipment_name;
      if (itemsRef.current.some((i) => i.equipmentId === eq.id)) return; // duplicates ignored
      let item: ReceiptItem | null = null;
      if (offline) {
        const cand = (await listReceiptCandidates()).find((c) => c.equipment_id === eq.id);
        if (cand) item = toItem(eq, { id: cand.transaction_id, kind: cand.checklist_kind, issued: cand.cuffs_issued, wardName: cand.ward_name });
      } else {
        // Cached open-transaction list (shared with the ward list): one fetch, not one per scan.
        const open = await queryClient.fetchQuery({ queryKey: ["active-borrows"], queryFn: listActiveBorrows, staleTime: 30_000 });
        let tx: TransactionOut | undefined = open.find((t) => t.equipment.id === eq.id);
        if (!tx) {
          // The cached list can predate a dispatch made moments ago (another
          // device, or this one): refetch ONCE before declaring "not dispatched".
          const fresh = await queryClient.fetchQuery({ queryKey: ["active-borrows"], queryFn: listActiveBorrows, staleTime: 0 });
          tx = fresh.find((t) => t.equipment.id === eq.id);
        }
        if (tx) {
          const kind: ChecklistKind = tx.checklist_kind ?? (await getDispatchCheck(eq.id)).checklist_kind;
          const issued = tx.dispatch_checks?.kind === "cryo_cuff" ? tx.dispatch_checks.cuffs : null;
          item = toItem(eq, { id: tx.id, kind, issued });
        }
      }
      if (!item) {
        setNotice(`⛔ ${label} ไม่ได้ถูกจ่ายออกไป ไม่ถูกเพิ่ม`);
        return;
      }
      setNotice(null);
      setDone([]);
      const add = item;
      setItems((prev) => (prev.some((i) => i.equipmentId === eq.id) ? prev : [...prev, add]));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [offline, queryClient],
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
        await addById(s.id);
      } catch (err) {
        setNotice(`⛔ ${apiErrorMessage(err, `ไม่พบเครื่อง ${text}`)} ไม่ถูกเพิ่ม`);
      } finally {
        setAdding(false);
      }
    },
    [offline, addById],
  );

  const addByQr = useCallback(
    async (raw: string) => {
      try {
        await addEquipment(await resolveEquipmentByQr(raw));
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

  const patch = (id: string, p: Partial<ReceiptItem>) =>
    setItems((prev) => prev.map((i) => (i.transactionId === id ? { ...i, ...p } : i)));
  const remove = (id: string) => {
    setItems((prev) => prev.filter((i) => i.transactionId !== id));
    setEditing(null);
  };

  const submit = async () => {
    if (items.length === 0 || submittingRef.current) return;
    submittingRef.current = true;
    setSubmitting(true);
    setNotice(null);
    const sent = items;
    const contactName = contact.trim() || null;
    try {
      if (offline) {
        const failed: ReceiptItem[] = [];
        let queued = 0;
        for (const it of sent) {
          try {
            await enqueueOfflineReceipt({
              transaction_id: it.transactionId,
              receipt_outcome: it.outcome,
              notes: note || undefined,
              ward_contact_name: contactName ?? undefined,
              receipt_checks: it.checks,
              ...(cuffsOf(it.checks) ? { cuffs_returned: cuffsOf(it.checks)! } : {}),
            });
            queued += 1;
          } catch (err) {
            failed.push({
              ...it,
              error: err instanceof LocalOpError || err instanceof OfflineStoreError ? err.message : "บันทึกในเครื่องไม่สำเร็จ",
            });
          }
        }
        setItems(failed);
        setQueuedCount((n) => n + queued);
        return;
      }
      const payload: ReceiptBatchItem[] = sent.map((it) => ({
        transaction_id: it.transactionId,
        receipt_outcome: it.outcome,
        checks: it.checks,
        cuffs_returned: cuffsOf(it.checks),
      }));
      const resp = await receiptBatch({
        ward_id: wardId || null,
        ward_contact_name: contactName,
        note: note.trim() || null,
        items: payload,
      });
      const ok: { bcm: string; ref: string }[] = [];
      const keep: ReceiptItem[] = [];
      sent.forEach((it, i) => {
        const r = resp.results.find((x) => x.index === i);
        if (r?.ok) ok.push({ bcm: it.bcm, ref: r.transaction_no ?? "" });
        else keep.push({ ...it, error: batchErrorText(r?.error?.code, r?.error?.message) });
      });
      if (ok.length > 0) {
        if (wardId) {
          setLastWard(wardId);
          bumpWardUsage(wardId);
        }
        setNote("");
        void queryClient.invalidateQueries({ queryKey: ["active-borrows"] });
      }
      setDone(ok);
      setItems(keep);
    } catch (err) {
      setNotice(apiErrorMessage(err, "รับคืนเครื่องมือไม่สำเร็จ"));
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto flex max-w-md flex-col gap-3 pb-6">
      {offline && <OfflineStaleGate />}
      <h1 className="text-lg font-semibold">รับคืนเครื่องมือ</h1>

      <div role="tablist" className="grid grid-cols-2 gap-2">
        {(
          [
            ["receive", "รับคืนเครื่อง"],
            ["cuffs", "รับ Cuff ค้าง"],
          ] as const
        ).map(([k, label]) => (
          <button
            key={k}
            role="tab"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={`min-h-11 rounded-lg px-3 py-2 text-sm font-medium ${tab === k ? "bg-status-borrowed/15 text-status-borrowed" : "surface"}`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "cuffs" ? (
        <CuffsOutstandingPanel offline={offline} />
      ) : (
        <>
          <WardSection
            title="หอผู้ป่วยที่ส่งคืน"
            contactLabel="ชื่อผู้ส่งคืน (Ward)"
            wards={wards}
            departments={departments}
            wardId={wardId}
            onWardChange={setWardId}
            contact={contact}
            onContact={setContact}
            phone={phone}
            onPhone={setPhone}
            showPhone={false}
          />

          {!offline && wardId && ward && (
            <section className="surface rounded-xl border p-3">
              <button
                type="button"
                aria-expanded={showOpen}
                onClick={() => setShowOpen((o) => !o)}
                className="flex min-h-11 w-full items-center justify-between text-sm font-medium"
              >
                <span>
                  เครื่องที่ค้างอยู่ {ward.name} ({wardOpen.length})
                </span>
                <span aria-hidden="true">{showOpen ? "▾" : "▸"}</span>
              </button>
              {showOpen && (
                <ul className="mt-2 flex flex-col gap-1.5">
                  {wardOpen.length === 0 && <li className="text-xs text-[var(--text-muted)]">ไม่มีเครื่องค้าง</li>}
                  {wardOpen.map((t) => (
                    <li key={t.id}>
                      <button
                        type="button"
                        aria-label={`เพิ่ม ${t.equipment.asset_number ?? t.equipment.equipment_name}`}
                        onClick={() => void addById(t.equipment.id)}
                        className="flex min-h-11 w-full items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-1.5 text-left text-sm"
                      >
                        <strong>{t.equipment.asset_number ?? t.equipment.equipment_name}</strong>
                        <span className="min-w-0 flex-1 truncate text-xs text-[var(--text-muted)]">{t.equipment.equipment_name}</span>
                        <span aria-hidden="true">＋</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

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
                const open = editing === it.transactionId;
                const cuffs = cuffsOf(it.checks);
                const partial = !!cuffs && !!it.issuedCuffs && totalCuffs(cuffs) < totalCuffs(it.issuedCuffs);
                return (
                  <li key={it.transactionId} className="flex flex-col gap-1">
                    {!open && (
                      <button
                        type="button"
                        aria-label={`แก้ไข ${it.bcm}`}
                        onClick={() => setEditing(it.transactionId)}
                        className="flex min-h-11 w-full items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-left"
                      >
                        <strong className="text-sm">{it.bcm}</strong>
                        <span className="min-w-0 flex-1 truncate text-xs text-[var(--text-muted)]">{it.name}</span>
                        {partial && <span className="whitespace-nowrap text-xs text-amber-400">Cuff {totalCuffs(cuffs)}/{totalCuffs(it.issuedCuffs)}</span>}
                        {it.outcome === "defective" && <span className="whitespace-nowrap text-xs font-medium text-status-repair">เสีย</span>}
                        <CheckGlyphs checks={it.checks} />
                        <span aria-hidden="true">›</span>
                      </button>
                    )}
                    {open && (
                      <ItemEditPanel
                        bcm={it.bcm}
                        name={it.name}
                        statusLine={it.kind === "cryo_cuff" ? "Cryo-Cuff" : "ตรวจสภาพอุปกรณ์"}
                        onRemove={() => remove(it.transactionId)}
                        onDone={() => setEditing(null)}
                      >
                        <ChecksEditor
                          checks={it.checks}
                          issuedCuffs={it.kind === "cryo_cuff" ? (it.issuedCuffs ?? undefined) : undefined}
                          onChange={(c) => patch(it.transactionId, { checks: c })}
                        />
                        <div>
                          <p className="mb-1 text-xs text-[var(--text-muted)]">ผลการรับคืน</p>
                          <div className="grid grid-cols-2 gap-2">
                            {OUTCOMES.map((o) => (
                              <button
                                key={o.value}
                                type="button"
                                aria-pressed={it.outcome === o.value}
                                onClick={() => patch(it.transactionId, { outcome: o.value })}
                                className={`min-h-11 rounded-lg border px-3 py-2 text-sm ${it.outcome === o.value ? o.cls : "border-[var(--border)]"}`}
                              >
                                {o.label}
                              </button>
                            ))}
                          </div>
                          {it.outcome === "usable" && hasAbnormal(it.checks) && (
                            <div role="alert" className="mt-2 rounded-lg border border-amber-500/60 bg-amber-500/10 p-2 text-sm">
                              <p>มีรายการไม่ปกติ – จะเปลี่ยนผลเป็น "เสีย" ไหม?</p>
                              <button
                                type="button"
                                onClick={() => patch(it.transactionId, { outcome: "defective" })}
                                className="mt-1 min-h-11 rounded-md bg-status-repair px-3 text-xs font-medium text-white"
                              >
                                เปลี่ยนเป็น "เสีย"
                              </button>
                            </div>
                          )}
                        </div>
                      </ItemEditPanel>
                    )}
                    {it.error && (
                      <p role="alert" className="px-1 text-xs text-status-repair">
                        ✗ {it.bcm}: {it.error}
                      </p>
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
            <ul aria-label="ผลการรับคืน" className="rounded-lg border border-status-available/40 bg-status-available/10 p-2 text-sm">
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
              disabled={submitting || items.length === 0}
              className="w-full rounded-xl bg-status-available py-3 text-base font-semibold text-white disabled:opacity-50"
            >
              {submitting ? "กำลังบันทึก..." : `ยืนยันการรับคืน (${items.length} เครื่อง)`}
            </button>
            <p className="text-xs text-[var(--text-muted)]">เวลาและกะบันทึกอัตโนมัติ</p>
          </div>
        </>
      )}
    </div>
  );
}
