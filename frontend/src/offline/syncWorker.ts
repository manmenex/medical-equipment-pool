import axios from "axios";

import { isUnreachableError } from "@/services/connectivity";
import { MAX_BATCH_OPS, postOperations, type SyncOperationResult } from "@/services/syncClient";
import { useAuthStore } from "@/store/authStore";

import {
  ackOperation,
  listOutbox,
  updateOutbox,
  type OutboxRecord,
} from "./offlineStore";

// PR25E S3 (docs/design/PR25D_OFFLINE_OPERATION_PLAN.md 7.4, 8.4, 9.1).
// Sends the CURRENT user's pending outbox rows in device_seq order, 25 per
// batch, one worker per device (Web Lock, with a localStorage-lease fallback).
// Deferred to later PRs: POST /sync/verify journal replay (B3), snapshot
// refresh (S4), clock-offset capture.

export const LOCK_NAME = "mep-sync";
export const LEASE_KEY = "mep-sync-lease";
export const LEASE_MS = 60_000;
export const INTERVAL_MS = 30_000;
export const BACKOFF_BASE_MS = 2_000;
export const BACKOFF_MAX_MS = 120_000;

export function computeBackoff(failures: number): number {
  if (failures <= 0) return 0;
  return Math.min(BACKOFF_BASE_MS * 2 ** (failures - 1), BACKOFF_MAX_MS);
}

export type SyncStatus = "idle" | "running" | "backoff" | "auth_required" | "stopped";
export interface SyncState {
  status: SyncStatus;
  failures: number;
  nextAttemptAt: number;
  lastError: string | null;
}

export type RunOutcome =
  | "done"
  | "skipped_locked"
  | "skipped_no_user"
  | "skipped_backoff"
  | "backoff"
  | "auth_required"
  | "aborted";

let state: SyncState = { status: "idle", failures: 0, nextAttemptAt: 0, lastError: null };
const listeners = new Set<(s: SyncState) => void>();
let running = false;

function setState(patch: Partial<SyncState>): void {
  state = { ...state, ...patch };
  listeners.forEach((l) => l(state));
}
export function getSyncState(): SyncState {
  return state;
}
export function subscribeSync(l: (s: SyncState) => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}
/** Test hook. */
export function resetSyncState(): void {
  state = { status: "idle", failures: 0, nextAttemptAt: 0, lastError: null };
  running = false;
}

/** The ONLY source of the acting user: the auth store (never caller input). */
function currentUserId(): string | null {
  const { user, accessToken } = useAuthStore.getState();
  return user && accessToken ? String(user.id) : null;
}

// ---- cross-tab single flight --------------------------------------------

async function withLock<T>(fn: () => Promise<T>): Promise<{ ran: true; value: T } | { ran: false }> {
  const locks = (typeof navigator !== "undefined" ? navigator.locks : undefined) as LockManager | undefined;
  if (locks?.request) {
    return locks.request(LOCK_NAME, { ifAvailable: true }, async (lock) => {
      if (!lock) return { ran: false as const };
      return { ran: true as const, value: await fn() };
    });
  }
  // Fallback: expiring lease in localStorage. Not atomic; the server's op_id
  // idempotency makes a lost race harmless (loser gets `duplicate`).
  const owner = globalThis.crypto.randomUUID();
  try {
    const raw = localStorage.getItem(LEASE_KEY);
    if (raw) {
      const lease = JSON.parse(raw) as { owner: string; expires: number };
      if (lease.expires > Date.now()) return { ran: false };
    }
    localStorage.setItem(LEASE_KEY, JSON.stringify({ owner, expires: Date.now() + LEASE_MS }));
  } catch {
    /* storage unavailable: proceed; server idempotency still protects */
  }
  try {
    return { ran: true, value: await fn() };
  } finally {
    try {
      const raw = localStorage.getItem(LEASE_KEY);
      if (raw && (JSON.parse(raw) as { owner: string }).owner === owner) localStorage.removeItem(LEASE_KEY);
    } catch {
      /* ignore */
    }
  }
}

// ---- hold logic (design 9.1 item 3) -------------------------------------

/** Equipment and transaction ids an op touches. A dispatch's op_id is its transaction id. */
export function dependencyKeys(rec: OutboxRecord): string[] {
  const env = rec.envelope as {
    dispatch?: { equipment_id?: unknown };
    receipt?: { transaction_id?: unknown };
  };
  const keys: string[] = [];
  const eq = env.dispatch?.equipment_id;
  if (typeof eq === "string") keys.push(`eq:${eq}`);
  if (env.dispatch) keys.push(`tx:${rec.op_id}`);
  const tx = env.receipt?.transaction_id;
  if (typeof tx === "string") keys.push(`tx:${tx}`);
  return keys;
}

/**
 * After conflict/rejected results: later pending ops of the same queue that
 * touch the same equipment/transaction become `held` (blocked_by = root op).
 */
export async function applyHolds(userId: string): Promise<void> {
  const rows = await listOutbox(userId);
  const blocked = new Map<string, string>();
  for (const rec of rows) {
    const keys = dependencyKeys(rec);
    if (rec.state === "conflict" || rec.state === "rejected") {
      for (const k of keys) if (!blocked.has(k)) blocked.set(k, rec.op_id);
    } else if (rec.state === "held" && rec.blocked_by) {
      for (const k of keys) if (!blocked.has(k)) blocked.set(k, rec.blocked_by);
    } else if (rec.state === "pending") {
      const hit = keys.find((k) => blocked.has(k));
      if (hit) {
        const by = blocked.get(hit)!;
        await updateOutbox(userId, rec.op_id, { state: "held", blocked_by: by });
        for (const k of keys) if (!blocked.has(k)) blocked.set(k, by);
      }
    }
  }
}

// ---- the run ------------------------------------------------------------

function errorStatus(e: unknown): number | undefined {
  return axios.isAxiosError(e) ? e.response?.status : undefined;
}

async function revert(userId: string, batch: OutboxRecord[], code: string | null): Promise<void> {
  for (const rec of batch) {
    try {
      await updateOutbox(userId, rec.op_id, { state: "pending", last_error_code: code ?? rec.last_error_code });
    } catch {
      /* acked/removed meanwhile */
    }
  }
}

async function runLocked(userId: string): Promise<RunOutcome> {
  // We hold the device lock, so nothing is really in flight: a `sending` row
  // is left over from a crashed/closed tab and is safe to re-send.
  for (const rec of await listOutbox(userId)) {
    if (rec.state === "sending") await updateOutbox(userId, rec.op_id, { state: "pending" });
  }
  await applyHolds(userId);

  const deferred = new Set<string>(); // retry_later this run
  let retryLater = false;
  for (;;) {
    if (currentUserId() !== userId) return "aborted"; // logout or user switch
    const sendable = (await listOutbox(userId)).filter((r) => r.state === "pending" && !deferred.has(r.op_id));
    if (sendable.length === 0) break;
    const batch = sendable.slice(0, MAX_BATCH_OPS);
    for (const rec of batch) {
      await updateOutbox(userId, rec.op_id, { state: "sending", attempt_count: rec.attempt_count + 1 });
    }

    let results: SyncOperationResult[];
    try {
      results = await postOperations(batch.map((r) => r.envelope));
    } catch (e) {
      const status = errorStatus(e);
      if (status === 401 || status === 403 || status === 423) {
        await revert(userId, batch, `HTTP_${status}`);
        setState({ status: "auth_required", lastError: `HTTP_${status}` });
        return "auth_required";
      }
      await revert(userId, batch, isUnreachableError(e) ? "UNREACHABLE" : status ? `HTTP_${status}` : "NETWORK");
      return "backoff";
    }
    // A response arriving after logout is still recorded below.

    const byId = new Map(results.map((r) => [r.op_id, r]));
    let malformed = false;
    for (const rec of batch) {
      const res = byId.get(rec.op_id);
      if (!res) {
        malformed = true;
        await revert(userId, [rec], "NO_RESULT");
        continue;
      }
      switch (res.result) {
        case "applied":
        case "duplicate":
          await ackOperation(userId, rec.op_id, res as unknown as Record<string, unknown>);
          break;
        case "conflict":
          await updateOutbox(userId, rec.op_id, { state: "conflict", last_error_code: res.code });
          break;
        case "rejected":
          await updateOutbox(userId, rec.op_id, { state: "rejected", last_error_code: res.code });
          break;
        case "retry_later":
          deferred.add(rec.op_id);
          retryLater = true;
          await updateOutbox(userId, rec.op_id, { state: "pending", last_error_code: res.code });
          break;
        default:
          malformed = true;
          await revert(userId, [rec], "UNKNOWN_RESULT");
      }
    }
    await applyHolds(userId);
    if (malformed) return "backoff";
  }
  return retryLater ? "backoff" : "done";
}

/** Run one sync round for the current user. Safe to call from any trigger. */
export async function syncNow(opts: { force?: boolean } = {}): Promise<RunOutcome> {
  const userId = currentUserId();
  if (!userId) return "skipped_no_user";
  if (running) return "skipped_locked";
  if (!opts.force && Date.now() < state.nextAttemptAt) return "skipped_backoff";
  running = true;
  setState({ status: "running" });
  try {
    const out = await withLock(() => runLocked(userId));
    if (!out.ran) {
      setState({ status: "idle" });
      return "skipped_locked";
    }
    const outcome = out.value;
    if (outcome === "backoff") {
      const failures = state.failures + 1;
      setState({ status: "backoff", failures, nextAttemptAt: Date.now() + computeBackoff(failures) });
    } else if (outcome === "done") {
      setState({ status: "idle", failures: 0, nextAttemptAt: 0, lastError: null });
    } else if (outcome === "aborted") {
      setState({ status: "idle" });
    }
    return outcome;
  } catch (e) {
    // Local storage failure etc.: back off, never crash the app.
    const failures = state.failures + 1;
    setState({
      status: "backoff",
      failures,
      nextAttemptAt: Date.now() + computeBackoff(failures),
      lastError: e instanceof Error ? e.message : "ERROR",
    });
    return "backoff";
  } finally {
    running = false;
  }
}

/** Call after enqueueOperation (S4 wiring). Respects backoff only if already failing. */
export function requestSync(): void {
  void syncNow({ force: state.status !== "backoff" && state.status !== "auth_required" });
}

/** Install triggers: online, visibility, interval, login/logout. Returns a stop function. */
export function startSyncWorker(): () => void {
  const trigger = () => void syncNow();
  const onOnline = () => void syncNow({ force: true });
  window.addEventListener("online", onOnline);
  const onVisible = () => {
    if (document.visibilityState === "visible") trigger();
  };
  document.addEventListener("visibilitychange", onVisible);
  const timer = setInterval(trigger, INTERVAL_MS);
  const unsub = useAuthStore.subscribe((s, prev) => {
    const id = s.user?.id ?? null;
    const prevId = prev.user?.id ?? null;
    if (id && id !== prevId) {
      setState({ status: "idle", failures: 0, nextAttemptAt: 0, lastError: null });
      void syncNow({ force: true }); // login
    } else if (!id && prevId) {
      setState({ status: "stopped" }); // logout: the run aborts at its next check
    }
  });
  trigger(); // app start
  return () => {
    window.removeEventListener("online", onOnline);
    document.removeEventListener("visibilitychange", onVisible);
    clearInterval(timer);
    unsub();
  };
}
