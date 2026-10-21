import { api } from "@/services/api";
import type {
  Category,
  Department,
  Location,
  Ward,
  WardPhoneImportResponse,
  WardPhoneImportRow,
} from "@/types";

export async function listDepartments(): Promise<Department[]> {
  return (await api.get<Department[]>("/departments")).data;
}

export async function listWards(): Promise<Ward[]> {
  return (await api.get<Ward[]>("/wards")).data;
}

export async function listLocations(): Promise<Location[]> {
  return (await api.get<Location[]>("/locations")).data;
}

export async function listCategories(): Promise<Category[]> {
  return (await api.get<Category[]>("/categories")).data;
}

// Roadmap PR25E slice S0: administrator-only phone edit / bulk import.
// The backend remains the authority (403 for non-admins).
export async function updateWardPhone(id: string, phone: string | null): Promise<Ward> {
  return (await api.patch<Ward>(`/wards/${id}`, { phone })).data;
}

export async function updateDepartmentPhone(id: string, phone: string | null): Promise<Department> {
  return (await api.patch<Department>(`/departments/${id}`, { phone })).data;
}

export async function importWardPhones(
  rows: WardPhoneImportRow[],
  opts: { dryRun: boolean; overwrite: boolean },
): Promise<WardPhoneImportResponse> {
  return (
    await api.post<WardPhoneImportResponse>(
      "/wards/phones/import",
      { rows },
      { params: { dry_run: opts.dryRun, overwrite: opts.overwrite } },
    )
  ).data;
}
