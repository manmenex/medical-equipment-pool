import { getMeta } from "./offlineStore";
import { getLastServerContactAt } from "./serverTime";

// PR25E S4 (design 9.8, Owner decision X4): N = 4 hours, a configurable constant.
export const STALE_THRESHOLD_MS = 4 * 60 * 60 * 1000;
export const AMBER_SNAPSHOT_MS = 12 * 60 * 60 * 1000; // design 3.2 / 14

export interface Staleness {
  /** Seconds since the last successful snapshot, or null when none exists. */
  snapshotAgeS: number | null;
  /** Seconds since the server was last reachable, or null when never. */
  offlineForS: number | null;
  stale: boolean;
}

export async function getLastSnapshotAt(): Promise<number | null> {
  try {
    const v = await getMeta<number>("last_snapshot_at");
    return typeof v === "number" ? v : null;
  } catch {
    return null;
  }
}

/** Pure rule: stale when either age exceeds N, or when there is no snapshot at all. */
export function evaluateStaleness(
  lastSnapshotAt: number | null,
  lastContactAt: number | null,
  now: number,
  thresholdMs: number = STALE_THRESHOLD_MS,
): Staleness {
  const snapshotAgeS = lastSnapshotAt === null ? null : Math.max(0, Math.round((now - lastSnapshotAt) / 1000));
  const offlineForS = lastContactAt === null ? null : Math.max(0, Math.round((now - lastContactAt) / 1000));
  const limitS = thresholdMs / 1000;
  const stale =
    snapshotAgeS === null || snapshotAgeS > limitS || (offlineForS !== null && offlineForS > limitS);
  return { snapshotAgeS, offlineForS, stale };
}

export async function getStaleness(now: number = Date.now()): Promise<Staleness> {
  return evaluateStaleness(await getLastSnapshotAt(), await getLastServerContactAt(), now);
}

// The acknowledgement is per session (page load / login), design 9.8: "before
// the operator keys the first dispatch or receipt in the session".
let acknowledged = false;
const listeners = new Set<() => void>();
export function isStaleAcknowledged(): boolean {
  return acknowledged;
}
export function acknowledgeStaleness(): void {
  acknowledged = true;
  listeners.forEach((l) => l());
}
export function resetStaleAcknowledgement(): void {
  acknowledged = false;
  listeners.forEach((l) => l());
}
export function subscribeStaleAck(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}
