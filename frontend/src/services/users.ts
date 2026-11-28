import { api } from "@/services/api";
import type { Role } from "@/types";

export interface ManagedUser {
  id: string;
  employee_code: string;
  full_name: string;
  email: string;
  role: Role;
  is_active: boolean;
}

export interface CreateUserInput {
  employee_code: string;
  full_name: string;
  email: string;
  password: string;
  role_name: Role;
}

export interface PasswordResetResult {
  employee_code: string;
  temporary_password: string;
}

// Administrator-only; the backend is the authority (403 otherwise).
export async function listUsers(): Promise<ManagedUser[]> {
  return (await api.get<ManagedUser[]>("/users")).data;
}

export async function createUser(input: CreateUserInput): Promise<ManagedUser> {
  return (await api.post<ManagedUser>("/users", input)).data;
}

export async function updateUser(
  id: string,
  patch: { role_name?: Role; is_active?: boolean },
): Promise<ManagedUser> {
  return (await api.patch<ManagedUser>(`/users/${id}`, patch)).data;
}

export async function resetUserPassword(id: string): Promise<PasswordResetResult> {
  return (await api.post<PasswordResetResult>(`/users/${id}/reset-password`)).data;
}
