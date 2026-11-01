import type { Department, Ward } from "@/types";

// Roadmap PR25E slice S0 (design 3.4 D2): ward phone first, then its
// department's phone. Returns "" when neither is set.
export function resolveWardPhone(
  ward: Pick<Ward, "phone" | "department_id"> | undefined | null,
  departments: Pick<Department, "id" | "phone">[] | undefined | null,
): string {
  if (!ward) return "";
  const own = ward.phone?.trim();
  if (own) return own;
  if (ward.department_id) {
    const dep = (departments ?? []).find((d) => d.id === ward.department_id);
    return dep?.phone?.trim() ?? "";
  }
  return "";
}
