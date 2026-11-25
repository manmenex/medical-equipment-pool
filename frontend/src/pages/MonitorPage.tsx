import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { useDebounce } from "@/hooks/useDebounce";
import { listWards } from "@/services/masterData";
import { fetchMonitorEvents, type MonitorEvent, type MonitorKind } from "@/services/monitor";

// Roadmap PR32 (D9/D13) base: read-only dispatch/receipt Monitor.
// Placeholders (intentionally NOT rendered): ward contact name (PR27, D7) and
// outstanding cuffs (PR28, D11).
export const MONITOR_REFRESH_MS = 30_000;

interface Submission {
  key: string;
  ward: string;
  operator: string;
  time: string;
  events: MonitorEvent[];
}

interface Group {
  key: string;
  date: string;
  shift: "day" | "night";
  submissions: Submission[];
  equipmentCount: number;
}

function hhmm(iso: string): string {
  return new Date(iso).toLocaleTimeString("th-TH", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Bangkok",
  });
}

function hhmmss(d: Date): string {
  return d.toLocaleTimeString("en-GB", { hour12: false, timeZone: "Asia/Bangkok" });
}

/** Mimics paper slips: same kind + ward + operator + minute = one submission. */
export function groupEvents(events: MonitorEvent[]): Group[] {
  const groups = new Map<string, Group>();
  const subs = new Map<string, Submission>();
  for (const e of events) {
    const gKey = `${e.business_date}|${e.shift}`;
    let g = groups.get(gKey);
    if (!g) {
      g = { key: gKey, date: e.business_date, shift: e.shift, submissions: [], equipmentCount: 0 };
      groups.set(gKey, g);
    }
    const minute = e.event_at.slice(0, 16);
    const sKey = `${gKey}|${e.kind}|${e.ward.id ?? ""}|${e.operator.id ?? e.operator.full_name ?? ""}|${minute}`;
    let s = subs.get(sKey);
    if (!s) {
      s = {
        key: sKey,
        ward: e.ward.name ?? "-",
        operator: e.operator.full_name ?? "-",
        time: hhmm(e.event_at),
        events: [],
      };
      subs.set(sKey, s);
      g.submissions.push(s);
    }
    s.events.push(e);
    g.equipmentCount += 1;
  }
  return [...groups.values()];
}

export function MonitorPage() {
  const [kind, setKind] = useState<MonitorKind>("dispatch");
  const [wardId, setWardId] = useState<string | null>(null);
  const [wardText, setWardText] = useState("");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const q = useDebounce(search.trim(), 300);

  const wards = useQuery({ queryKey: ["wards"], queryFn: listWards, staleTime: 5 * 60_000 });

  const makeQuery = (k: MonitorKind) => ({
    queryKey: ["monitor-events", k, wardId, q],
    queryFn: () =>
      fetchMonitorEvents({ kind: k, ward_id: wardId ?? undefined, q: q || undefined, limit: 200 }),
    refetchInterval: MONITOR_REFRESH_MS,
  });
  const dispatchQ = useQuery(makeQuery("dispatch"));
  const receiptQ = useQuery(makeQuery("receipt"));
  const active = kind === "dispatch" ? dispatchQ : receiptQ;

  const updatedAt = Math.max(dispatchQ.dataUpdatedAt, receiptQ.dataUpdatedAt);
  const groups = useMemo(() => groupEvents(active.data?.items ?? []), [active.data]);

  const wardMatches = useMemo(() => {
    const t = wardText.trim().toLowerCase();
    if (!t) return [];
    return (wards.data ?? []).filter((w) => w.name.toLowerCase().includes(t)).slice(0, 8);
  }, [wards.data, wardText]);
  const selectedWard = (wards.data ?? []).find((w) => w.id === wardId);

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-3 p-4">
      <h1 className="text-xl font-semibold">Monitor การจ่าย/รับ</h1>

      <div role="tablist" className="grid grid-cols-2 gap-2">
        {(
          [
            ["dispatch", "จ่าย", dispatchQ.data?.total],
            ["receipt", "รับ", receiptQ.data?.total],
          ] as const
        ).map(([k, label, count]) => (
          <button
            key={k}
            role="tab"
            aria-selected={kind === k}
            onClick={() => setKind(k)}
            className={`rounded-lg px-3 py-2 text-sm font-medium ${
              kind === k ? "bg-status-borrowed/15 text-status-borrowed" : "surface"
            }`}
          >
            {label} ({count ?? 0})
          </button>
        ))}
      </div>

      <div className="flex flex-col gap-2">
        <input
          aria-label="ค้นหาหอผู้ป่วย"
          placeholder="ค้นหาหอผู้ป่วย"
          value={wardText}
          onChange={(e) => setWardText(e.target.value)}
          className="surface rounded-lg border px-3 py-2 text-sm"
        />
        <div className="flex flex-wrap gap-2">
          {selectedWard && (
            <button
              type="button"
              aria-label={`ล้างตัวกรอง ${selectedWard.name}`}
              onClick={() => setWardId(null)}
              className="rounded-full bg-status-borrowed/15 px-3 py-1 text-xs text-status-borrowed"
            >
              {selectedWard.name} ×
            </button>
          )}
          {wardMatches
            .filter((w) => w.id !== wardId)
            .map((w) => (
              <button
                key={w.id}
                type="button"
                onClick={() => {
                  setWardId(w.id);
                  setWardText("");
                }}
                className="surface rounded-full border px-3 py-1 text-xs"
              >
                {w.name}
              </button>
            ))}
        </div>
        <input
          aria-label="ค้นหา BCM / ชื่อผู้ปฏิบัติ"
          placeholder="ค้นหา BCM / ชื่อผู้ปฏิบัติ"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="surface rounded-lg border px-3 py-2 text-sm"
        />
      </div>

      <p className="text-xs text-[var(--text-muted)]" data-testid="monitor-updated">
        อัปเดตล่าสุด {updatedAt ? hhmmss(new Date(updatedAt)) : "--:--:--"}
      </p>

      {active.isError && <p role="alert">ไม่สามารถโหลดข้อมูลได้</p>}
      {!active.isLoading && !active.isError && groups.length === 0 && <p>ไม่มีรายการ</p>}

      {groups.map((g) => (
        <section key={g.key} aria-label={`${g.date} ${g.shift}`} className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold">
            {g.date} · {g.shift === "day" ? "Day" : "Night"}{" "}
            <span className="font-normal text-[var(--text-muted)]">
              ({g.submissions.length} ครั้ง / {g.equipmentCount} เครื่อง)
            </span>
          </h2>
          {g.submissions.map((s) => {
            const expanded = !!open[s.key];
            return (
              <div key={s.key} className="surface rounded-lg border">
                <button
                  type="button"
                  aria-expanded={expanded}
                  onClick={() => setOpen((o) => ({ ...o, [s.key]: !o[s.key] }))}
                  className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm"
                >
                  <span>
                    <strong>{s.ward}</strong> · {s.operator}
                  </span>
                  <span className="whitespace-nowrap text-xs">
                    {s.time} · {s.events.length} เครื่อง
                  </span>
                </button>
                {expanded && (
                  <ul className="border-t px-3 py-2 text-sm">
                    {s.events.map((e) => (
                      <li key={e.id}>
                        {e.equipment.bcm_code ?? e.equipment.name}
                        {e.kind === "receipt" && e.receipt_outcome && (
                          <span className="ml-2 text-xs">
                            ({e.receipt_outcome === "usable" ? "ใช้งานได้" : "ชำรุด"})
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </section>
      ))}
    </div>
  );
}
