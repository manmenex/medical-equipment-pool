import { api } from "@/services/api";
import type { Category, Department, Location, Ward } from "@/types";

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
