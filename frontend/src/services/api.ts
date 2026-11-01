import axios, { type AxiosError } from "axios";

import { captureFromResponseHeaders } from "@/offline/serverTime";
import { isUnreachableError, setMarkedOffline } from "@/services/connectivity";
import { useAuthStore } from "@/store/authStore";
import type { ApiError } from "@/types";

export const api = axios.create({
  baseURL: "/api/v1",
  withCredentials: true,
});

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// PR25E S1: a refresh failure only ends the session when the server gives a
// real authentication verdict. Network errors, timeouts and 5xx keep the
// session (the operator may be offline), mark the app offline, and are retried
// later with exponential backoff.
const AUTH_FAILURE_STATUSES = new Set([401, 403, 423]);
const BACKOFF_BASE_MS = 2_000;
const BACKOFF_MAX_MS = 120_000;

let refreshPromise: Promise<RefreshOutcome> | null = null;
let transientFailures = 0;
let nextRefreshAllowedAt = 0;

/** Test hook: reset backoff state. */
export function resetRefreshState(): void {
  refreshPromise = null;
  transientFailures = 0;
  nextRefreshAllowedAt = 0;
}

type RefreshOutcome = { kind: "token"; token: string } | { kind: "unreachable" } | { kind: "denied" };

async function refreshAccessToken(): Promise<RefreshOutcome> {
  try {
    const resp = await axios.post<{ access_token: string }>(
      "/api/v1/auth/refresh",
      {},
      { withCredentials: true }
    );
    const token = resp.data.access_token;
    useAuthStore.getState().setAccessToken(token);
    transientFailures = 0;
    nextRefreshAllowedAt = 0;
    setMarkedOffline(false);
    return { kind: "token", token };
  } catch (err) {
    if (isUnreachableError(err)) {
      transientFailures += 1;
      const delay = Math.min(BACKOFF_BASE_MS * 2 ** (transientFailures - 1), BACKOFF_MAX_MS);
      nextRefreshAllowedAt = Date.now() + delay;
      setMarkedOffline(true);
      return { kind: "unreachable" };
    }
    const status = axios.isAxiosError(err) ? err.response?.status : undefined;
    const code = axios.isAxiosError(err) ? (err.response?.data as ApiError | undefined)?.code : undefined;
    // Forced password change: keep the session; the route redirect handles it.
    if (status === 403 && code === "PASSWORD_CHANGE_REQUIRED") {
      return { kind: "denied" };
    }
    // Only a real authentication verdict ends the session; any other
    // unexpected client error is not proof the session is invalid.
    if (status !== undefined && AUTH_FAILURE_STATUSES.has(status)) {
      useAuthStore.getState().logout();
    }
    return { kind: "denied" };
  }
}

function singleFlightRefresh(): Promise<RefreshOutcome> {
  // Offline backoff window: do not hammer the server; fail fast, keep session.
  if (Date.now() < nextRefreshAllowedAt) return Promise.resolve({ kind: "unreachable" });
  refreshPromise ??= refreshAccessToken().finally(() => {
    refreshPromise = null;
  });
  return refreshPromise;
}

api.interceptors.response.use(
  (response) => {
    setMarkedOffline(false);
    // PR25E S4: every successful response is a server-time reading (design 11).
    captureFromResponseHeaders(response.headers);
    return response;
  },
  async (error: AxiosError<ApiError>) => {
    const original = error.config;
    if (isUnreachableError(error)) setMarkedOffline(true);
    // The backend refuses every route but /auth/me and /auth/change-password
    // while an administrator-set password is pending. The route guard
    // normally prevents getting here; this covers a stale profile. A full
    // navigation also drops any cached query state fetched before the change.
    if (error.response?.status === 403 && error.response.data?.code === "PASSWORD_CHANGE_REQUIRED") {
      if (window.location.pathname !== "/change-password") {
        window.location.assign("/change-password");
      }
      return Promise.reject(error);
    }
    if (error.response?.status === 401 && original && !(original as { _retry?: boolean })._retry) {
      (original as { _retry?: boolean })._retry = true;
      const outcome = await singleFlightRefresh();
      if (outcome.kind === "token") {
        original.headers = original.headers ?? {};
        original.headers.Authorization = `Bearer ${outcome.token}`;
        return api.request(original);
      }
    }
    return Promise.reject(error);
  }
);

export function apiErrorMessage(error: unknown, fallback = "เกิดข้อผิดพลาด กรุณาลองใหม่"): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as ApiError | undefined;
    return data?.detail ?? fallback;
  }
  return fallback;
}

// Roadmap PR8C (backend/app/core/exceptions.py's DomainError subclasses):
// the stable, machine-readable `code` field every backend error response
// carries. Callers that need to branch on the specific cause of a failure
// (e.g. ReturnPage distinguishing RECEIPT_RACE_LOST from
// TRANSACTION_ALREADY_RETURNED) must read this, never `detail` -- `detail`
// is a human-readable, free-text message not intended as a stable contract
// for behavior branching.
export function apiErrorCode(error: unknown): string | undefined {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as ApiError | undefined;
    return data?.code;
  }
  return undefined;
}
