import { api } from "@/services/api";
import type { UserProfile } from "@/types";

export async function login(identifier: string, password: string) {
  const resp = await api.post<{ access_token: string; expires_in: number }>("/auth/login", {
    identifier,
    password,
  });
  return resp.data;
}

export async function fetchMe(): Promise<UserProfile> {
  const resp = await api.get<UserProfile>("/auth/me");
  return resp.data;
}

export async function logout(): Promise<void> {
  await api.post("/auth/logout");
}
