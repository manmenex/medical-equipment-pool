import axios from "axios";

// PR25E S1 (docs/design/PR25D_OFFLINE_OPERATION_PLAN.md section 8.4).
// "Unreachable" means the server could not be reached or answered with a
// gateway/proxy failure. It is never an authentication verdict, so callers
// must keep the session. A 401/403/423 from the server is NOT unreachable.

const UNREACHABLE_STATUSES = new Set([408, 502, 503, 504]);

export function isUnreachableError(error: unknown): boolean {
  if (!axios.isAxiosError(error)) return false;
  const response = error.response;
  // No response at all: network error, DNS, offline, timeout, CORS/redirect to
  // an identity provider that the browser blocked.
  if (!response) return true;
  if (UNREACHABLE_STATUSES.has(response.status)) return true;
  // 5xx in general is a server fault, not a statement about the session.
  if (response.status >= 500) return true;
  // An HTML body on an API call means a captive portal / Cloudflare Access
  // login page answered instead of the API.
  const contentType = String(response.headers?.["content-type"] ?? "");
  if (contentType.includes("text/html")) return true;
  return false;
}

type Listener = (offline: boolean) => void;
let offline = false;
const listeners = new Set<Listener>();

export function isMarkedOffline(): boolean {
  return offline;
}

export function setMarkedOffline(value: boolean): void {
  if (offline === value) return;
  offline = value;
  listeners.forEach((l) => l(value));
}

export function subscribeOffline(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
