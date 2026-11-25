import { getMeta, putMetaIfAbsent, type HnBlob, type OutboxRecord } from "./offlineStore";

// Roadmap PR29 (Owner Governance 2026-11-25 D1): the offline queue is an HN
// surface. A queued dispatch's patient HN is encrypted with AES-GCM under a
// per-device, NON-EXTRACTABLE WebCrypto key kept in IndexedDB (the raw key
// bytes can never be read back, not even by this app), is stored on the outbox
// row (never in the envelope), is decrypted only to build the request body in
// `envelopeForSend`, and is deleted from the device when the server answers
// (offlineStore.ackOperation / updateOutbox / discard). Nothing here logs.
//
// Limits (documented in docs/api/sync.md): the key sits in the same browser
// profile as the ciphertext, so this protects against storage-level reads
// (profile copy, IndexedDB dump, backups), not against script running inside
// this origin. WebCrypto needs a secure context (HTTPS or localhost); on plain
// http:// LAN pages `crypto.subtle` is missing and an offline HN is refused
// rather than stored in clear.

export type { HnBlob };

export class HnVaultError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "HnVaultError";
  }
}

const KEY_META = "hn_device_key";

function subtle(): SubtleCrypto | null {
  const c = (globalThis as { crypto?: Crypto }).crypto;
  return c && c.subtle && typeof c.subtle.generateKey === "function" ? c.subtle : null;
}

export function hnEncryptionAvailable(): boolean {
  return subtle() !== null;
}

function toB64(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}

function fromB64(text: string): Uint8Array<ArrayBuffer> {
  const s = atob(text);
  const out = new Uint8Array(new ArrayBuffer(s.length));
  for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
  return out;
}

async function deviceKey(create: boolean): Promise<CryptoKey | null> {
  const s = subtle();
  if (!s) throw new HnVaultError("WebCrypto is unavailable");
  const existing = await getMeta<CryptoKey>(KEY_META);
  if (existing) return existing;
  if (!create) return null;
  const fresh = await s.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  return (await putMetaIfAbsent(KEY_META, fresh)) as CryptoKey;
}

export async function encryptHn(hn: string): Promise<HnBlob> {
  const s = subtle();
  if (!s) throw new HnVaultError("WebCrypto is unavailable");
  try {
    const key = (await deviceKey(true)) as CryptoKey;
    const iv = globalThis.crypto.getRandomValues(new Uint8Array(12));
    const ct = new Uint8Array(await s.encrypt({ name: "AES-GCM", iv }, key, new TextEncoder().encode(hn)));
    return { v: 1, iv: toB64(iv), ct: toB64(ct) };
  } catch (e) {
    if (e instanceof HnVaultError) throw e;
    throw new HnVaultError("HN encryption failed");
  }
}

/** Plaintext HN, or null when it cannot be decrypted (key gone / data damaged). */
export async function decryptHn(blob: HnBlob): Promise<string | null> {
  const s = subtle();
  if (!s) return null;
  try {
    const key = await deviceKey(false);
    if (!key) return null;
    const plain = await s.decrypt({ name: "AES-GCM", iv: fromB64(blob.iv) }, key, fromB64(blob.ct));
    return new TextDecoder().decode(plain);
  } catch {
    return null;
  }
}

/**
 * The request body for an outbox row: the stored envelope, plus `dispatch.hn`
 * when the row carries an encrypted HN that still decrypts. An HN that cannot
 * be decrypted is dropped (the dispatch itself must not be blocked by it).
 */
export async function envelopeForSend(rec: OutboxRecord): Promise<Record<string, unknown>> {
  if (!rec.hn_enc) return rec.envelope;
  const dispatch = (rec.envelope as { dispatch?: Record<string, unknown> }).dispatch;
  if (!dispatch) return rec.envelope;
  const hn = await decryptHn(rec.hn_enc);
  if (!hn) return rec.envelope;
  return { ...rec.envelope, dispatch: { ...dispatch, hn } };
}
