import { useQuery } from "@tanstack/react-query";

import { fetchMe } from "@/services/auth";
import { useAuthStore } from "@/store/authStore";
import type { Role, UserProfile } from "@/types";

export function useAuth() {
  const accessToken = useAuthStore((s) => s.accessToken);
  const storedUser = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);

  const query = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      const profile = await fetchMe();
      setUser(profile);
      return profile;
    },
    enabled: Boolean(accessToken),
    initialData: storedUser ?? undefined,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  return {
    user: query.data ?? null,
    isAuthenticated: Boolean(accessToken),
    isLoading: query.isLoading,
  };
}

// Roadmap PR10 (Role Model Consolidation): Thai display labels for the
// confirmed 3-role model. Display-only -- the backend never sends or
// expects these strings, only the role value itself (see types/index.ts's
// Role).
const ROLE_LABELS: Record<string, string> = {
  administrator: "ผู้ดูแลระบบ",
  equipment_pool_staff: "เจ้าหน้าที่ Equipment Pool",
  read_only: "ผู้ใช้ทั่วไป (ดูอย่างเดียว)",
};

export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}

// ---------------------------------------------------------------------------
// Roadmap PR10 (Role Model Consolidation): centralized frontend capability
// layer mirroring backend/app/api/v1/deps.py's capability groups
// (EQUIPMENT_POOL_OPERATION_ROLES, ADMINISTRATOR_ONLY_ROLES,
// VIEW_AND_REPORT_ROLES) exactly. Every place in the frontend that decides
// whether to show or hide an action must call one of these functions --
// never compare user.role against a literal role string inline. None of
// this is a security boundary: it only hides an action the backend would
// reject with 403 anyway, so it exists purely for usability (don't offer a
// button that will fail), and every caller must still handle a 403
// response safely regardless of what these functions return (the backend
// remains the sole authority).
// ---------------------------------------------------------------------------

type RoleLike = Pick<UserProfile, "role"> | null | undefined;

function hasRole(user: RoleLike, ...roles: Role[]): boolean {
  return user != null && (roles as string[]).includes(user.role);
}

// Dispatch, receipt, ward correction, and marking equipment defective.
// Mirrors backend EQUIPMENT_POOL_OPERATION_ROLES.
export function canCorrectTransactionWard(user: RoleLike): boolean {
  return hasRole(user, "administrator", "equipment_pool_staff");
}

export function canMarkEquipmentDefective(user: RoleLike): boolean {
  return hasRole(user, "administrator", "equipment_pool_staff");
}

// Administrator-only capabilities. Mirrors backend ADMINISTRATOR_ONLY_ROLES.
export function canManageEquipmentMasterData(user: RoleLike): boolean {
  return hasRole(user, "administrator");
}

export function canReactivateEquipment(user: RoleLike): boolean {
  return hasRole(user, "administrator");
}

export function canDecommissionEquipment(user: RoleLike): boolean {
  return hasRole(user, "administrator");
}

export function canManageUsers(user: RoleLike): boolean {
  return hasRole(user, "administrator");
}

// Roadmap PR12 (Inventory Import): mirrors backend
// app.api.v1.inventory_import's ADMINISTRATOR_ONLY_ROLES gate.
export function canImportInventory(user: RoleLike): boolean {
  return hasRole(user, "administrator");
}

// Dispatch/receipt entry points (borrow/return). Read Only never performs
// these -- mirrors backend EQUIPMENT_POOL_OPERATION_ROLES (app.api.v1.borrow.
// BORROW_ROLES).
export function canDispatchOrReceiveEquipment(user: RoleLike): boolean {
  return hasRole(user, "administrator", "equipment_pool_staff");
}

// Roadmap PR19B (Legacy Import Frontend Skeleton): mirrors the now-merged
// PR19A backend's real authorization boundary -- every
// /import-sessions endpoint (backend/app/api/v1/import_sessions.py) is
// gated by ADMINISTRATOR_ONLY_ROLES, the same tier as canImportInventory's
// PR12 precedent. This is a usability-only mirror of that backend rule,
// not the enforcement boundary itself -- the backend remains the real
// authority.
export function canManageLegacyImport(user: RoleLike): boolean {
  return hasRole(user, "administrator");
}
