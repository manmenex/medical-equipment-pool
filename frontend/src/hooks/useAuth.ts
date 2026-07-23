import { useQuery } from "@tanstack/react-query";

import { fetchMe } from "@/services/auth";
import { useAuthStore } from "@/store/authStore";
import type { UserProfile } from "@/types";

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

const ROLE_LABELS: Record<string, string> = {
  admin: "ผู้ดูแลระบบ",
  biomedical_engineer: "วิศวกรชีวการแพทย์",
  ward_nurse: "พยาบาลหอผู้ป่วย",
  transport_staff: "เจ้าหน้าที่ขนส่ง",
  viewer: "ผู้ใช้ทั่วไป",
};

export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}

// Roadmap PR9B (backend/app/api/v1/deps.py's WARD_CORRECTION_ROLES): a
// frontend-only usability gate mirroring the merged PR9A backend's
// temporary, intentionally conservative admin-only authorization
// (docs/audits/03-hospital-equipment-pool-workflow-audit.md §10 -- the
// current 5-role model has no confirmed, evidence-backed equivalent of the
// future "Equipment Pool Staff" role, so only admin is granted pending
// Roadmap PR10's Role Model Consolidation). This hides the action for a
// role the backend would reject with 403 -- it is NOT a security boundary
// by itself; the backend remains authoritative, and every caller of the
// correction API must still handle a 403 response safely regardless of
// this check (see WardCorrectionDialog). Single, centralized place for
// Roadmap PR10 to update when the confirmed 3-role model lands -- update
// ONLY this function, mirroring app.api.v1.deps.WARD_CORRECTION_ROLES.
export function canCorrectTransactionWard(user: Pick<UserProfile, "role"> | null | undefined): boolean {
  return user?.role === "admin";
}
