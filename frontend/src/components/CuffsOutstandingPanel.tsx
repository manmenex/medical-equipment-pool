import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ScanBar } from "@/components/entry/ScanBar";
import { apiErrorCode, apiErrorMessage } from "@/services/api";
import { batchErrorText, CUFF_TYPES, totalCuffs } from "@/services/checks";
import { resolveEquipmentByQr } from "@/services/equipment";
import { getOutstandingCuffs, receiveCuffs, type OutstandingCuffTx } from "@/services/cuffs";
import type { Cuffs, CuffType } from "@/types";

export const CUFFS_REFRESH_MS = 60_000;

export function cuffSummary(c: Cuffs): string {
  return CUFF_TYPES.filter((t) => c[t.key] > 0)
    .map((t) => `${t.label} ${c[t.key]}`)
    .join(" · ");
}

function ReceiveRow({ tx, wardName, onDone }: { tx: OutstandingCuffTx; wardName: string | null; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [counts, setCounts] = useState<Cuffs>(tx.cuffs);
  const [contact, setContact] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const submit = async () => {
    const send: Partial<Cuffs> = {};
    for (const t of CUFF_TYPES) if (counts[t.key] > 0) send[t.key] = counts[t.key];
    if (Object.keys(send).length === 0) return;
    setBusy(true);
    setMsg(null);
    try {
      await receiveCuffs(tx.transaction_id, send, contact.trim() || null);
      setMsg({ ok: true, text: "✓ รับ Cuff แล้ว" });
      setOpen(false);
      onDone();
    } catch (err) {
      setMsg({ ok: false, text: batchErrorText(apiErrorCode(err), apiErrorMessage(err, "รับ Cuff ไม่สำเร็จ")) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="flex flex-col gap-1">
      <button
        type="button"
        aria-expanded={open}
        aria-label={`รับ Cuff ${tx.bcm_code ?? tx.equipment_name}`}
        onClick={() => setOpen((o) => !o)}
        className="flex min-h-11 w-full items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-left"
      >
        <strong className="text-sm">{tx.bcm_code ?? tx.equipment_name}</strong>
        <span className="min-w-0 flex-1 truncate text-xs text-[var(--text-muted)]">{wardName ?? "-"}</span>
        <span className="whitespace-nowrap text-xs text-amber-400">{cuffSummary(tx.cuffs)}</span>
        <span aria-hidden="true">›</span>
      </button>
      {open && (
        <div role="group" aria-label={`รับ Cuff ${tx.bcm_code ?? ""}`} className="surface flex flex-col gap-2 rounded-lg border-2 border-status-borrowed p-3">
          {!tx.device_received ? (
            <p className="text-xs text-amber-400">เครื่องยังไม่ถูกรับคืน — บันทึก Cuff พร้อมการรับเครื่องในแท็บ "รับคืนเครื่อง"</p>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-2">
                {CUFF_TYPES.map((t) => (
                  <label key={t.key} className="flex items-center gap-2 text-sm">
                    <span className="flex-1">{t.label}</span>
                    <input
                      type="number"
                      min={0}
                      max={tx.cuffs[t.key]}
                      aria-label={`จำนวน ${t.label}`}
                      disabled={tx.cuffs[t.key] === 0}
                      value={counts[t.key]}
                      onChange={(e) => {
                        const v = Math.max(0, Math.min(tx.cuffs[t.key], Math.trunc(Number(e.target.value) || 0)));
                        setCounts((c) => ({ ...c, [t.key as CuffType]: v }));
                      }}
                      className="min-h-11 w-16 rounded border border-[var(--border)] bg-transparent px-2 py-1 text-center text-sm disabled:opacity-40"
                    />
                  </label>
                ))}
              </div>
              <input
                aria-label="ชื่อผู้ส่งคืน (Ward)"
                placeholder="ชื่อผู้ส่งคืน (Ward)"
                value={contact}
                maxLength={100}
                onChange={(e) => setContact(e.target.value)}
                className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm"
              />
              <button
                type="button"
                disabled={busy || totalCuffs(counts) === 0}
                onClick={() => void submit()}
                className="min-h-11 rounded-lg bg-status-available py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                {busy ? "กำลังบันทึก..." : "บันทึกรับ Cuff"}
              </button>
            </>
          )}
        </div>
      )}
      {msg && (
        <p role={msg.ok ? "status" : "alert"} className={`px-1 text-xs ${msg.ok ? "text-status-available" : "text-status-repair"}`}>
          {msg.text}
        </p>
      )}
    </li>
  );
}

interface Props {
  /** Receive mode lets staff record cuffs handed back later; the Monitor uses a read-only list. */
  readOnly?: boolean;
  offline?: boolean;
}

// Roadmap PR28 (D11): outstanding Cryo-Cuffs grouped by ward (GET /cuffs/outstanding).
export function CuffsOutstandingPanel({ readOnly = false, offline = false }: Props) {
  const qc = useQueryClient();
  const [filter, setFilter] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["cuffs-outstanding"],
    queryFn: () => getOutstandingCuffs(),
    refetchInterval: CUFFS_REFRESH_MS,
    enabled: !offline,
  });

  if (offline) {
    return <p className="text-sm text-[var(--text-muted)]">การรับ Cuff ค้างต้องออนไลน์ (ไม่รองรับการบันทึกแบบออฟไลน์)</p>;
  }

  const q = filter.trim().toLowerCase();
  const wards = (data?.items ?? [])
    .map((w) => ({
      ...w,
      transactions: w.transactions.filter(
        (t) => !q || (t.bcm_code ?? "").toLowerCase().includes(q) || t.equipment_name.toLowerCase().includes(q),
      ),
    }))
    .filter((w) => w.transactions.length > 0);

  return (
    <div className="flex flex-col gap-3">
      {!readOnly && (
        <ScanBar
          onBcm={setFilter}
          onQr={(raw) =>
            void resolveEquipmentByQr(raw)
              .then((eq) => {
                setNotice(null);
                setFilter(eq.bcm_code ?? eq.equipment_name);
              })
              .catch((err) => setNotice(apiErrorMessage(err, "ไม่พบเครื่องมือจาก QR ที่สแกน")))
          }
        />
      )}
      {filter && (
        <button type="button" onClick={() => setFilter("")} className="self-start rounded-full bg-status-borrowed/15 px-3 py-1 text-xs text-status-borrowed">
          {filter} ×
        </button>
      )}
      {notice && <p role="alert" className="text-sm text-status-repair">{notice}</p>}
      {isLoading && <p className="text-sm">กำลังโหลด...</p>}
      {isError && <p role="alert" className="text-sm">ไม่สามารถโหลดข้อมูล Cuff ค้างได้</p>}
      {data && wards.length === 0 && <p className="text-sm">ไม่มี Cuff ค้าง</p>}
      {wards.map((w) => (
        <section key={w.ward_id ?? "none"} aria-label={`Cuff ค้าง ${w.ward_name ?? "-"}`} className="flex flex-col gap-1.5">
          <h3 className="text-sm font-semibold">
            {w.ward_name ?? "-"} <span className="font-normal text-amber-400">({cuffSummary(w.cuffs)} · รวม {w.total})</span>
          </h3>
          <ul className="flex flex-col gap-1.5">
            {w.transactions.map((t) =>
              readOnly ? (
                <li key={t.transaction_id} className="flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm">
                  <strong>{t.bcm_code ?? t.equipment_name}</strong>
                  <span className="min-w-0 flex-1 truncate text-xs text-[var(--text-muted)]">{t.equipment_name}</span>
                  <span className="whitespace-nowrap text-xs text-amber-400">{cuffSummary(t.cuffs)}</span>
                </li>
              ) : (
                <ReceiveRow
                  key={t.transaction_id}
                  tx={t}
                  wardName={w.ward_name}
                  onDone={() => void qc.invalidateQueries({ queryKey: ["cuffs-outstanding"] })}
                />
              ),
            )}
          </ul>
        </section>
      ))}
    </div>
  );
}
