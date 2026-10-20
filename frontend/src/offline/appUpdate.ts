import { listAllActiveOutboxCount } from "./offlineStore";

// PR25E S6 (docs/design/PR25D_OFFLINE_OPERATION_PLAN.md 13.3): prompt-style
// PWA updates. A waiting service worker never reloads the page by itself; the
// operator applies it from the notice, and only when it is safe:
//   - no outbox op is pending / sending / held (on this device, any user), and
//   - no dispatch/receipt form is dirty, and
//   - the sync worker is not mid-send.
// Reloading discards nothing in IndexedDB, but an in-flight request or an
// unsaved form would be lost, so those block the apply.

export interface UpdateState {
  /** A new version is downloaded and waiting. */
  ready: boolean;
  /** The server told us this build's envelope is too old (CLIENT_TOO_OLD). */
  required: boolean;
}

let state: UpdateState = { ready: false, required: false };
let applyFn: (() => Promise<void>) | null = null;
const listeners = new Set<(s: UpdateState) => void>();
const dirtyForms = new Map<symbol, boolean>();

function emit(patch: Partial<UpdateState>): void {
  state = { ...state, ...patch };
  listeners.forEach((l) => l(state));
}

export function getUpdateState(): UpdateState {
  return state;
}
export function subscribeUpdate(l: (s: UpdateState) => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

/** Called by the service-worker registration (pwa.ts) with the activate-and-reload function. */
export function setUpdateReady(apply: () => Promise<void>): void {
  applyFn = apply;
  emit({ ready: true });
}

/** Called by the sync worker on a `CLIENT_TOO_OLD` reply. The queue is untouched. */
export function markClientTooOld(): void {
  emit({ required: true });
}

/** Form guard: a dirty dispatch/receipt form blocks applying an update. */
export function registerFormDirty(token: symbol, dirty: boolean): () => void {
  if (dirty) dirtyForms.set(token, true);
  else dirtyForms.delete(token);
  return () => {
    dirtyForms.delete(token);
  };
}
export function hasDirtyForm(): boolean {
  return dirtyForms.size > 0;
}

export type UpdateBlock = "form_dirty" | "ops_pending" | "sync_sending" | "storage_unreadable";

/** Why an update must wait right now, or null when it is safe to apply. */
export async function updateBlockReason(syncRunning: boolean): Promise<UpdateBlock | null> {
  if (hasDirtyForm()) return "form_dirty";
  if (syncRunning) return "sync_sending";
  try {
    if ((await listAllActiveOutboxCount()) > 0) return "ops_pending";
  } catch {
    // Cannot prove the queue is empty: do not reload.
    return "storage_unreadable";
  }
  return null;
}

/** Apply the waiting update if safe. Returns the blocking reason, or null if applied. */
export async function applyUpdateIfSafe(syncRunning: boolean): Promise<UpdateBlock | null> {
  const block = await updateBlockReason(syncRunning);
  if (block) return block;
  if (applyFn) await applyFn();
  else window.location.reload(); // CLIENT_TOO_OLD with no waiting worker: plain reload
  return null;
}

/** Test hook. */
export function resetAppUpdate(): void {
  state = { ready: false, required: false };
  applyFn = null;
  dirtyForms.clear();
}
