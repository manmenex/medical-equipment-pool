import { useCallback, useEffect, useRef, useState } from "react";

export type DbState = "online" | "offline" | "db_down";

const POLL_MS = 30_000;
const TIMEOUT_MS = 5_000;

const VIEW: Record<DbState, { label: string; title: string; color: string }> = {
  online: {
    label: "ออนไลน์",
    title: "เชื่อมต่อฐานข้อมูลปกติ",
    color: "#15803D",
  },
  offline: {
    label: "ออฟไลน์",
    title: "อุปกรณ์ไม่ได้เชื่อมต่ออินเทอร์เน็ต (ระบบคิวออฟไลน์ยังทำงาน)",
    color: "#A16207",
  },
  db_down: {
    label: "ฐานข้อมูลขัดข้อง",
    title: "เชื่อมต่อเซิร์ฟเวอร์ไม่ได้ หรือฐานข้อมูลไม่พร้อมใช้งาน",
    color: "#B91C1C",
  },
};

// Unauthenticated GET /api/v1/ready: 200 = DB ok, 503 = DB not ready. Only the
// HTTP status is used; the body (incl. redis) is never read or displayed.
async function checkReady(): Promise<DbState> {
  if (typeof navigator !== "undefined" && navigator.onLine === false) return "offline";
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch("/api/v1/ready", { cache: "no-store", signal: ctrl.signal });
    return res.ok ? "online" : "db_down";
  } catch {
    return navigator.onLine === false ? "offline" : "db_down";
  } finally {
    clearTimeout(timer);
  }
}

export function DbStatusLight() {
  const [state, setState] = useState<DbState>(
    typeof navigator !== "undefined" && navigator.onLine === false ? "offline" : "online",
  );

  const inFlight = useRef(false);
  const refresh = useCallback(() => {
    if (inFlight.current) return;
    inFlight.current = true;
    void checkReady()
      .then(setState)
      .finally(() => {
        inFlight.current = false;
      });
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, POLL_MS);
    const onOffline = () => setState("offline");
    window.addEventListener("focus", refresh);
    window.addEventListener("online", refresh);
    window.addEventListener("offline", onOffline);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", refresh);
      window.removeEventListener("online", refresh);
      window.removeEventListener("offline", onOffline);
    };
  }, [refresh]);

  const v = VIEW[state];
  return (
    <span
      role="status"
      data-testid="db-status"
      data-state={state}
      title={v.title}
      aria-label={`${v.label}: ${v.title}`}
      className="flex items-center gap-1 whitespace-nowrap text-xs text-[var(--text-muted)]"
    >
      <span
        aria-hidden="true"
        data-testid="db-status-dot"
        className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
        style={{ backgroundColor: v.color }}
      />
      <span>{v.label}</span>
    </span>
  );
}
