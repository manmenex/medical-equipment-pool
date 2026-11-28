import { useAuthStore } from "@/store/authStore";
import type { BcmSuggestion, Checks, ChecklistKind, Cuffs, DispatchType, Equipment, EquipmentSource, EquipmentStatus, ReceiptOutcome, RoutineRound } from "@/types";

import {
  enqueueOperation,
  listActiveEnvelopes,
  listOutbox,
  listRefs,
  rememberUserName,
  type OutboxRecord,
} from "./offlineStore";
import { encryptHn, HnVaultError } from "./hnVault";
import { getClockOffset } from "./serverTime";
import { getStaleness, isStaleAcknowledged } from "./staleness";
import { requestSync } from "./syncWorker";

// PR25E S4 (design 3, 7.2, 9.8): the offline dispatch/receipt write path.
// Identification is BCM Code search over the cached equipment only (D1): no QR,
// no Item No, no Asset Number ever reaches or leaves these functions. The
// acting operator is read from the auth store, never from caller input.

export type LocalOpErrorCode =
  | "NO_USER"
  | "DUPLICATE_LOCAL"
  | "NOT_AVAILABLE"
  | "NOT_FOUND"
  | "STALE_NOT_ACKNOWLEDGED"
  // Roadmap PR29: this device cannot keep an HN encrypted at rest.
  | "HN_UNAVAILABLE";

export class LocalOpError extends Error {
  readonly code: LocalOpErrorCode;
  constructor(code: LocalOpErrorCode, message: string) {
    super(message);
    this.name = "LocalOpError";
    this.code = code;
  }
}

/** Generic on purpose: never says whose entry it is or what it contains (design 8.1). */
export const DUPLICATE_LOCAL_MESSAGE = "มีรายการของเครื่องนี้ที่ยังไม่ได้ส่งอยู่ในเครื่องนี้แล้ว ไม่สามารถบันทึกซ้ำได้";

function rememberCurrentName(): void {
  const { user } = useAuthStore.getState();
  if (user) void rememberUserName(String(user.id), user.full_name);
}

function currentUserId(): string {
  const { user, accessToken } = useAuthStore.getState();
  if (!user || !accessToken) throw new LocalOpError("NO_USER", "ต้องเข้าสู่ระบบก่อนบันทึกรายการ");
  return String(user.id);
}

// ---- BCM search over the cache -------------------------------------------

/** Same prefix rule as backend `strip_bcm_prefix` (query side only). */
export function stripBcmPrefix(raw: string): string {
  let token = raw.trim();
  if (token.slice(0, 3).toUpperCase() === "BCM") token = token.slice(3);
  return token.trim();
}

interface CachedEquipment {
  id: string;
  bcm_code?: string | null;
  equipment_name?: string;
  category_name?: string | null;
  // Roadmap PR28: absent in a snapshot cached before this field existed.
  checklist_kind?: ChecklistKind | null;
  status?: EquipmentStatus;
  // Roadmap PR33 (D14): absent in a snapshot cached before these fields existed.
  equipment_source?: EquipmentSource;
  returned_to_owner?: boolean;
}

/**
 * Mirrors `crud.equipment.search_bcm`: case-insensitive substring match on
 * bcm_code only; exact match first, then shorter code, then alphabetical.
 */
export function rankBcmMatches<T extends { bcm_code?: string | null }>(rows: T[], q: string, limit = 10): T[] {
  const token = stripBcmPrefix(q);
  if (!token) return [];
  const upper = token.toUpperCase();
  const exact = new Set([upper, `BCM${upper}`]);
  return rows
    .filter((r) => typeof r.bcm_code === "string" && r.bcm_code.toUpperCase().includes(upper))
    .sort((a, b) => {
      const ea = exact.has(a.bcm_code!.toUpperCase()) ? 0 : 1;
      const eb = exact.has(b.bcm_code!.toUpperCase()) ? 0 : 1;
      return ea - eb || a.bcm_code!.length - b.bcm_code!.length || a.bcm_code!.localeCompare(b.bcm_code!);
    })
    .slice(0, limit);
}

export async function searchCachedBcm(q: string, limit = 10): Promise<BcmSuggestion[]> {
  const rows = (await listRefs("ref_equipment")) as CachedEquipment[];
  // A device returned to its owner leaves the pickers (D14).
  return rankBcmMatches(
    rows.filter((r) => !r.returned_to_owner),
    q,
    limit,
  ).map((r) => ({ id: r.id, bcm_code: r.bcm_code as string }));
}

// ---- local state on top of the snapshot ----------------------------------

interface EnvelopeView {
  op_type?: string;
  op_id?: string;
  dispatch?: { equipment_id?: string };
  receipt?: { transaction_id?: string; receipt_outcome?: ReceiptOutcome };
}

/** Unsent (pending/sending/held) ops of ALL users on this device, attribution removed. */
async function activeOps(): Promise<EnvelopeView[]> {
  return (await listActiveEnvelopes()) as EnvelopeView[];
}

function receiptTargets(ops: EnvelopeView[]): Map<string, ReceiptOutcome | undefined> {
  const m = new Map<string, ReceiptOutcome | undefined>();
  for (const o of ops) {
    const tx = o.receipt?.transaction_id;
    if (typeof tx === "string") m.set(tx, o.receipt?.receipt_outcome);
  }
  return m;
}

/** Equipment ids with an unsent dispatch whose transaction has no unsent receipt. */
function locallyDispatchedEquipment(ops: EnvelopeView[]): Set<string> {
  const received = receiptTargets(ops);
  const out = new Set<string>();
  for (const o of ops) {
    const eq = o.dispatch?.equipment_id;
    if (typeof eq === "string" && o.op_id && !received.has(o.op_id)) out.add(eq);
  }
  return out;
}

/**
 * Status of a cached equipment row with this device's own unsent operations
 * applied on top (design 3.2): a pending dispatch shows as issued, a pending
 * receipt of its open transaction shows the receipt's outcome.
 */
export async function effectiveCachedEquipment(
  id: string,
): Promise<{ equipment: Equipment; locallyDispatched: boolean }> {
  const cached = ((await listRefs("ref_equipment")) as CachedEquipment[]).find((r) => r.id === id);
  if (!cached) throw new LocalOpError("NOT_FOUND", "ไม่พบเครื่องมือในข้อมูลที่เก็บไว้ในเครื่อง");
  const ops = await activeOps();
  const locallyDispatched = locallyDispatchedEquipment(ops).has(id);
  let status: EquipmentStatus = cached.status ?? "available_at_pool";
  if (locallyDispatched) {
    status = "issued_to_ward";
  } else if (status === "issued_to_ward") {
    const received = receiptTargets(ops);
    const open = ((await listRefs("ref_open_tx")) as Array<{ id: string; equipment_id?: string }>).find(
      (t) => t.equipment_id === id,
    );
    const outcome = open ? received.get(open.id) : undefined;
    if (outcome === "usable") status = "available_at_pool";
    else if (outcome === "defective") status = "unavailable_defective";
  }
  const equipment: Equipment = {
    id,
    asset_number: null, // never cached (D1)
    serial_number: null,
    equipment_name: cached.equipment_name ?? "",
    category_id: null,
    brand: null,
    model: null,
    department_owner_id: null,
    current_location_id: null,
    status,
    bcm_code: cached.bcm_code ?? null,
    pm_due_date: null,
    cal_due_date: null,
    created_at: "",
    updated_at: "",
    equipment_source: cached.equipment_source ?? "pool",
    // The snapshot carries only a flag, not the timestamp.
    returned_to_owner_at: cached.returned_to_owner ? "returned" : null,
  };
  return { equipment, locallyDispatched };
}

/** Cached checklist kind; old caches without the field fall back to the category name (/cryo/i). */
export async function cachedChecklistKind(id: string): Promise<ChecklistKind> {
  const c = ((await listRefs("ref_equipment")) as CachedEquipment[]).find((r) => r.id === id);
  if (c?.checklist_kind === "cryo_cuff" || c?.checklist_kind === "standard") return c.checklist_kind;
  return /cryo/i.test(c?.category_name ?? "") ? "cryo_cuff" : "standard";
}

/** Matches backend CURRENT_ENVELOPE_VERSION (backend/app/schemas/sync.py). */
export const ENVELOPE_VERSION = 1;

// ---- envelopes ------------------------------------------------------------

async function baseEnvelope(userId: string, opType: "dispatch" | "receipt", now: number) {
  const offset = await getClockOffset();
  return {
    // S6: lets the server accept this client for one release after a contract change.
    envelope_version: ENVELOPE_VERSION,
    user_id: userId,
    op_type: opType,
    occurred_at_local: new Date(now).toISOString(),
    ...(offset ? { clock_offset_ms: offset.ms } : {}),
  };
}

async function staleLocal(now: number): Promise<{ stale_context: boolean; snapshot_age_s: number | null }> {
  const st = await getStaleness(now);
  if (st.stale && !isStaleAcknowledged()) {
    throw new LocalOpError("STALE_NOT_ACKNOWLEDGED", "กรุณารับทราบคำเตือนข้อมูลล้าสมัยก่อนบันทึกรายการ");
  }
  return { stale_context: st.stale, snapshot_age_s: st.snapshotAgeS };
}

export interface OfflineDispatchInput {
  equipment_id: string;
  ward_id: string;
  // Roadmap PR26: optional legacy values; the dispatch form no longer sends them.
  dispatch_type?: DispatchType;
  routine_round?: RoutineRound;
  phone_number?: string;
  notes?: string;
  // Roadmap PR27/PR28: shared ward contact name + accessory checklist per op.
  ward_contact_name?: string;
  dispatch_checks?: Checks;
  /**
   * Roadmap PR29 (D1): optional patient HN. Encrypted with the per-device key
   * before it is written; it is never part of the stored envelope.
   */
  hn?: string;
}

export const HN_OFFLINE_UNAVAILABLE_MESSAGE =
  "เครื่องนี้เก็บ HN แบบเข้ารหัสในโหมดออฟไลน์ไม่ได้ ลบ HN ออกแล้วบันทึกใหม่ หรือรอเชื่อมต่อเครือข่าย";

export async function enqueueOfflineDispatch(input: OfflineDispatchInput): Promise<OutboxRecord> {
  const userId = currentUserId();
  const now = Date.now();
  const local = await staleLocal(now);
  const { equipment, locallyDispatched } = await effectiveCachedEquipment(input.equipment_id);
  if (locallyDispatched) throw new LocalOpError("DUPLICATE_LOCAL", DUPLICATE_LOCAL_MESSAGE);
  if (equipment.status !== "available_at_pool") {
    throw new LocalOpError("NOT_AVAILABLE", "เครื่องนี้ไม่พร้อมให้เบิก");
  }
  const dispatch: Record<string, unknown> = {
    equipment_id: input.equipment_id,
    ward_id: input.ward_id,
  };
  if (input.dispatch_type) dispatch.dispatch_type = input.dispatch_type;
  if (input.dispatch_type === "routine_round" && input.routine_round) dispatch.routine_round = input.routine_round;
  if (input.phone_number) dispatch.phone_number = input.phone_number;
  if (input.notes) dispatch.notes = input.notes;
  if (input.ward_contact_name) dispatch.ward_contact_name = input.ward_contact_name;
  if (input.dispatch_checks) dispatch.dispatch_checks = input.dispatch_checks;
  let hn_enc;
  if (input.hn && input.hn.trim()) {
    try {
      hn_enc = await encryptHn(input.hn.trim());
    } catch (e) {
      if (e instanceof HnVaultError) throw new LocalOpError("HN_UNAVAILABLE", HN_OFFLINE_UNAVAILABLE_MESSAGE);
      throw e;
    }
  }
  const rec = await enqueueOperation(userId, {
    body: { ...(await baseEnvelope(userId, "dispatch", now)), dispatch },
    local,
    ...(hn_enc ? { hn_enc } : {}),
  });
  rememberCurrentName();
  requestSync();
  return rec;
}

export interface OfflineReceiptInput {
  transaction_id: string;
  receipt_outcome: ReceiptOutcome;
  notes?: string;
  ward_contact_name?: string;
  receipt_checks?: Checks;
  cuffs_returned?: Partial<Cuffs>;
}

export async function enqueueOfflineReceipt(input: OfflineReceiptInput): Promise<OutboxRecord> {
  const userId = currentUserId();
  const now = Date.now();
  const local = await staleLocal(now);
  if (receiptTargets(await activeOps()).has(input.transaction_id)) {
    throw new LocalOpError("DUPLICATE_LOCAL", DUPLICATE_LOCAL_MESSAGE);
  }
  const receipt: Record<string, unknown> = {
    transaction_id: input.transaction_id,
    receipt_outcome: input.receipt_outcome,
  };
  if (input.notes) receipt.notes = input.notes;
  if (input.ward_contact_name) receipt.ward_contact_name = input.ward_contact_name;
  if (input.receipt_checks) receipt.receipt_checks = input.receipt_checks;
  if (input.cuffs_returned) receipt.cuffs_returned = input.cuffs_returned;
  const rec = await enqueueOperation(userId, {
    body: { ...(await baseEnvelope(userId, "receipt", now)), receipt },
    local,
  });
  rememberCurrentName();
  requestSync();
  return rec;
}

// ---- receipt candidates ---------------------------------------------------

export interface ReceiptCandidate {
  /** Receipt is addressed by this id only (D7). */
  transaction_id: string;
  equipment_id: string;
  bcm_code: string | null;
  equipment_name: string;
  ward_id: string | null;
  ward_name: string | null;
  /** ISO time; for local dispatches this is the local entry time. */
  borrowed_at: string;
  source: "snapshot" | "local";
  /** Roadmap PR28: checklist kind and issued cuffs (null when unknown / none). */
  checklist_kind: ChecklistKind;
  cuffs_issued: Cuffs | null;
}

/**
 * Open transactions from the snapshot plus THIS user's unsent offline
 * dispatches, minus anything that already has an unsent receipt on this device.
 */
export async function listReceiptCandidates(): Promise<ReceiptCandidate[]> {
  const userId = currentUserId();
  const [equipment, wards, openTx, mine, ops] = await Promise.all([
    listRefs("ref_equipment") as Promise<CachedEquipment[]>,
    listRefs("ref_wards") as Promise<Array<{ id: string; name?: string }>>,
    listRefs("ref_open_tx") as Promise<
      Array<{ id: string; equipment_id?: string; ward_id?: string; borrowed_at?: string; checklist_kind?: ChecklistKind | null; cuffs_issued?: Cuffs | null }>
    >,
    listOutbox(userId),
    activeOps(),
  ]);
  const eqById = new Map(equipment.map((e) => [e.id, e]));
  const wardName = new Map(wards.map((w) => [w.id, w.name ?? null]));
  const received = receiptTargets(ops);
  const out: ReceiptCandidate[] = [];
  const mk = (
    id: string,
    equipment_id: string,
    ward_id: string | null,
    borrowed_at: string,
    source: ReceiptCandidate["source"],
    kind: ChecklistKind,
    cuffs: Cuffs | null,
  ): ReceiptCandidate => ({
    transaction_id: id,
    equipment_id,
    bcm_code: eqById.get(equipment_id)?.bcm_code ?? null,
    equipment_name: eqById.get(equipment_id)?.equipment_name ?? "",
    ward_id,
    ward_name: ward_id ? (wardName.get(ward_id) ?? null) : null,
    borrowed_at,
    source,
    checklist_kind: kind,
    cuffs_issued: cuffs,
  });
  for (const t of openTx) {
    if (received.has(t.id) || !t.equipment_id) continue;
    const kind = t.checklist_kind ?? (await cachedChecklistKind(t.equipment_id));
    out.push(mk(t.id, t.equipment_id, t.ward_id ?? null, t.borrowed_at ?? "", "snapshot", kind, t.cuffs_issued ?? null));
  }
  const seen = new Set(out.map((c) => c.transaction_id));
  for (const rec of mine) {
    if (rec.state !== "pending" && rec.state !== "sending" && rec.state !== "held") continue;
    const env = rec.envelope as {
      op_type?: string;
      occurred_at_local?: string;
      dispatch?: { equipment_id?: string; ward_id?: string; dispatch_checks?: Checks };
    };
    if (env.op_type !== "dispatch" || !env.dispatch?.equipment_id) continue;
    if (received.has(rec.op_id) || seen.has(rec.op_id)) continue;
    const dc = env.dispatch.dispatch_checks;
    out.push(
      mk(
        rec.op_id,
        env.dispatch.equipment_id,
        env.dispatch.ward_id ?? null,
        env.occurred_at_local ?? "",
        "local",
        dc?.kind ?? (await cachedChecklistKind(env.dispatch.equipment_id)),
        dc?.kind === "cryo_cuff" ? dc.cuffs : null,
      ),
    );
  }
  return out.sort((a, b) => (a.bcm_code ?? "").localeCompare(b.bcm_code ?? ""));
}

/** Count of the current user's unsent items (pending badge). */
export async function countMyUnsent(): Promise<number> {
  const { user, accessToken } = useAuthStore.getState();
  if (!user || !accessToken) return 0;
  return (await listOutbox(String(user.id))).filter(
    (r) => r.state === "pending" || r.state === "sending" || r.state === "held",
  ).length;
}

/** Count of the current user's local ops the server flagged as conflict (waiting for staff review). */
export async function countMyConflicts(): Promise<number> {
  const { user, accessToken } = useAuthStore.getState();
  if (!user || !accessToken) return 0;
  return (await listOutbox(String(user.id))).filter((r) => r.state === "conflict").length;
}
