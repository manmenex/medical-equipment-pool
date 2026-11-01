import { login } from "@/services/auth";
import { MAX_BATCH_OPS, postOperations, type SyncOperationResult } from "@/services/syncClient";
import { useAuthStore } from "@/store/authStore";

import {
  ackOperation,
  getUserNames,
  listOtherUsersOutbox,
  listRefs,
  updateOutbox,
  type OutboxRecord,
} from "./offlineStore";
import { dependencyKeys } from "./syncWorker";

// PR25E S5b (design 8.3, Owner decision D4): explicit adoption of ops that
// other users left in this device's outbox. Pool staff / administrator only,
// online only, never automatic, and only after a fresh password login (the
// server independently rejects adoption by a token older than 15 minutes with
// ADOPT_REAUTH_REQUIRED). Only counts, type, BCM and time are exposed.

export interface AdoptableOp {
  op_id: string;
  original_user_id: string;
  op_type: string;
  bcm_code: string | null;
  occurred_at: string | null;
}

export interface AdoptableGroup {
  user_id: string;
  /** Cached display name, or null when this device never saw it. */
  name: string | null;
  count: number;
  ops: AdoptableOp[];
}

/**
 * Rows that still need sending: never conflicts/rejections (already answered)
 * or held ones. `sending` counts as sendable: the original user is logged out
 * on this device (the adopter is the one logged in), so no worker of theirs is
 * really mid-flight; the row is left over from a closed tab and the server's
 * op_id idempotency makes a re-send safe.
 */
function isSendable(r: OutboxRecord): boolean {
  return r.state === "pending" || r.state === "sending";
}

export async function listAdoptableGroups(currentUserId: string): Promise<AdoptableGroup[]> {
  const rows = (await listOtherUsersOutbox(currentUserId)).filter(isSendable);
  if (rows.length === 0) return [];
  const names = await getUserNames();
  const bcmById = new Map<string, string>();
  try {
    for (const e of await listRefs("ref_equipment")) {
      const bcm = (e as { bcm_code?: unknown }).bcm_code;
      if (typeof bcm === "string") bcmById.set(e.id, bcm);
    }
  } catch {
    /* BCM is a convenience; the op type and time are enough */
  }
  const groups = new Map<string, AdoptableGroup>();
  for (const r of rows) {
    const env = r.envelope as {
      op_type?: string;
      occurred_at_local?: string;
      dispatch?: { equipment_id?: string };
    };
    let g = groups.get(r.user_id);
    if (!g) {
      g = { user_id: r.user_id, name: names[r.user_id] ?? null, count: 0, ops: [] };
      groups.set(r.user_id, g);
    }
    g.count += 1;
    g.ops.push({
      op_id: r.op_id,
      original_user_id: r.user_id,
      op_type: env.op_type ?? "",
      bcm_code: env.dispatch?.equipment_id ? (bcmById.get(env.dispatch.equipment_id) ?? null) : null,
      occurred_at: env.occurred_at_local ?? null,
    });
  }
  return [...groups.values()];
}

export class ReauthError extends Error {}

/** Fresh login with the current user's own identifier; replaces the access token. */
export async function reauthenticate(password: string): Promise<void> {
  const user = useAuthStore.getState().user;
  if (!user || !password) throw new ReauthError("NO_USER");
  const { access_token } = await login(user.employee_code, password);
  useAuthStore.getState().setAccessToken(access_token);
}

export interface AdoptSummary {
  applied: number;
  duplicate: number;
  conflict: number;
  rejected: number;
  /** retry_later, reauth-required, blocked behind a failed op, or never reached. */
  left_pending: number;
  reauth_required: boolean;
  /** Request-level failure (network / HTTP status); remaining ops stay pending. */
  error: string | null;
}

const emptySummary = (): AdoptSummary => ({
  applied: 0,
  duplicate: 0,
  conflict: 0,
  rejected: 0,
  left_pending: 0,
  reauth_required: false,
  error: null,
});

/**
 * Send the selected users' pending ops with `adopt: true`. Each op stays
 * recorded under its original user locally (ack/updates use the row's own
 * user_id); the server records the original as operator and the caller as
 * sender. A failed/conflicting op holds later ops touching the same
 * equipment/transaction (they stay pending, as in the normal worker).
 */
export async function adoptOps(
  currentUserId: string,
  originalUserIds: ReadonlySet<string>,
  isOnline: () => boolean = () => (typeof navigator === "undefined" ? true : navigator.onLine !== false),
): Promise<AdoptSummary> {
  const summary = emptySummary();
  if (!isOnline()) {
    summary.error = "OFFLINE";
    return summary;
  }
  const all = (await listOtherUsersOutbox(currentUserId)).filter((r) => originalUserIds.has(r.user_id));
  // Mirror the worker's hold logic (applyHolds): in device_seq order, a
  // conflict/rejected/held row blocks later rows touching the same
  // equipment/transaction, so they are not sent ahead of it.
  const blocked = new Set<string>();
  const queue: OutboxRecord[] = [];
  for (const r of all) {
    const keys = dependencyKeys(r);
    if (!isSendable(r)) {
      for (const k of keys) blocked.add(k);
      continue;
    }
    if (keys.some((k) => blocked.has(k))) {
      summary.left_pending += 1;
      continue;
    }
    queue.push(r);
  }

  for (let i = 0; i < queue.length; i += MAX_BATCH_OPS) {
    const batch = queue.slice(i, i + MAX_BATCH_OPS);
    let results: SyncOperationResult[];
    try {
      results = await postOperations(
        batch.map((r) => ({ ...r.envelope, adopt: true, original_user_id: r.user_id })),
      );
    } catch (e) {
      const status = (e as { response?: { status?: number } } | null)?.response?.status;
      summary.error = status ? `HTTP_${status}` : "NETWORK";
      summary.left_pending += queue.length - i;
      return summary;
    }
    const byId = new Map(results.map((r) => [r.op_id, r]));
    for (const rec of batch) {
      const res = byId.get(rec.op_id);
      if (!res) {
        summary.left_pending += 1;
        continue;
      }
      switch (res.result) {
        case "applied":
        case "duplicate":
          await ackOperation(rec.user_id, rec.op_id, res as unknown as Record<string, unknown>);
          summary[res.result] += 1;
          break;
        case "conflict":
          await updateOutbox(rec.user_id, rec.op_id, { state: "conflict", last_error_code: res.code });
          summary.conflict += 1;
          for (const k of dependencyKeys(rec)) blocked.add(k);
          break;
        case "rejected":
          if (res.code === "ADOPT_REAUTH_REQUIRED") {
            summary.reauth_required = true;
            summary.left_pending += 1;
            break;
          }
          await updateOutbox(rec.user_id, rec.op_id, { state: "rejected", last_error_code: res.code });
          summary.rejected += 1;
          for (const k of dependencyKeys(rec)) blocked.add(k);
          break;
        default:
          summary.left_pending += 1; // retry_later: stays pending
      }
    }
    if (summary.reauth_required) {
      summary.left_pending += queue.length - i - batch.length;
      return summary;
    }
  }
  return summary;
}
