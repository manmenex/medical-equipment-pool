import { useQuery } from "@tanstack/react-query";

import { fetchMe } from "@/services/auth";
import { useAuthStore } from "@/store/authStore";

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
