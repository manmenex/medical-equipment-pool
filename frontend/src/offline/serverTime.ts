import { getMeta, setMeta } from "./offlineStore";

// PR25E S4 (docs/design/PR25D_OFFLINE_OPERATION_PLAN.md section 11): clock
// offset capture. SIGN CONVENTION: offset = serverTime - localTime, so
// `serverTime = localTime + offset` and the server computes
// `occurred_at = occurred_at_local + clock_offset_ms`. A device clock that is
// 5 minutes slow therefore has a POSITIVE offset of 300000.

export const META_CLOCK_OFFSET = "clock_offset_ms";
export const META_CLOCK_MEASURED_AT = "clock_offset_measured_at";
export const META_LAST_CONTACT = "last_server_contact_at";
/** Persist at most this often for the high-frequency Date-header path. */
const PERSIST_EVERY_MS = 30_000;

export function computeClockOffsetMs(serverTimeMs: number, localTimeMs: number): number {
  return Math.round(serverTimeMs - localTimeMs);
}

export interface ClockOffset {
  ms: number;
  measuredAt: number;
}

let memOffset: ClockOffset | null = null;
let memContact: number | null = null;
let lastPersist = 0;

/** Test hook. */
export function resetServerTimeState(): void {
  memOffset = null;
  memContact = null;
  lastPersist = 0;
}

async function persist(): Promise<void> {
  try {
    if (memOffset) {
      await setMeta(META_CLOCK_OFFSET, memOffset.ms);
      await setMeta(META_CLOCK_MEASURED_AT, memOffset.measuredAt);
    }
    if (memContact !== null) await setMeta(META_LAST_CONTACT, memContact);
  } catch {
    /* offline storage unavailable: the in-memory value still serves this tab */
  }
}

/**
 * Record a server time reading taken at local time `localNow`. Also counts as
 * "server reachable now". Returns the offset in ms.
 */
export async function recordServerTime(
  serverTimeMs: number,
  localNow: number = Date.now(),
  opts: { force?: boolean } = {},
): Promise<number> {
  const ms = computeClockOffsetMs(serverTimeMs, localNow);
  memOffset = { ms, measuredAt: localNow };
  memContact = localNow;
  if (opts.force || localNow - lastPersist >= PERSIST_EVERY_MS) {
    lastPersist = localNow;
    await persist();
  }
  return ms;
}

/** A response with no usable time still proves the server was reachable. */
export function noteServerContact(localNow: number = Date.now()): void {
  memContact = localNow;
}

/**
 * Hook for the axios success interceptor: reads the `Date` header. HTTP dates
 * have 1 s resolution (truncated), so half a second is added to centre the
 * error. Never throws.
 */
export function captureFromResponseHeaders(headers: unknown, localNow: number = Date.now()): void {
  try {
    const raw = (headers as Record<string, unknown> | undefined)?.["date"];
    const parsed = typeof raw === "string" ? Date.parse(raw) : NaN;
    if (Number.isNaN(parsed)) {
      noteServerContact(localNow);
      return;
    }
    void recordServerTime(parsed + 500, localNow).catch(() => undefined);
  } catch {
    /* ignore */
  }
}

export async function getClockOffset(): Promise<ClockOffset | null> {
  if (memOffset) return memOffset;
  try {
    const ms = await getMeta<number>(META_CLOCK_OFFSET);
    const measuredAt = await getMeta<number>(META_CLOCK_MEASURED_AT);
    if (typeof ms === "number" && typeof measuredAt === "number") return { ms, measuredAt };
  } catch {
    /* ignore */
  }
  return null;
}

export async function getLastServerContactAt(): Promise<number | null> {
  if (memContact !== null) return memContact;
  try {
    const v = await getMeta<number>(META_LAST_CONTACT);
    return typeof v === "number" ? v : null;
  } catch {
    return null;
  }
}
