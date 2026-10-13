import axios, { type AxiosError } from "axios";

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

let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  try {
    const resp = await axios.post<{ access_token: string }>(
      "/api/v1/auth/refresh",
      {},
      { withCredentials: true }
    );
    const token = resp.data.access_token;
    useAuthStore.getState().setAccessToken(token);
    return token;
  } catch {
    useAuthStore.getState().logout();
    return null;
  }
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiError>) => {
    const original = error.config;
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
      refreshPromise = refreshPromise ?? refreshAccessToken();
      const token = await refreshPromise;
      refreshPromise = null;
      if (token) {
        original.headers = original.headers ?? {};
        original.headers.Authorization = `Bearer ${token}`;
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
