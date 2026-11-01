import type { PropsWithChildren } from "react";
import { Link } from "react-router-dom";

import { canManageLegacyImport, useAuth } from "@/hooks/useAuth";

// PR19B: frontend visibility only, never a security boundary (see
// hooks/useAuth.ts's canManageLegacyImport note) -- a real PR19A backend
// endpoint would still need its own authorization check. Shared by all
// three PR19B routes so "permission denied" renders identically regardless
// of entry point (nav link vs. a typed-in URL).
export function LegacyImportAccessGate({ children }: PropsWithChildren) {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return <p className="text-sm text-[var(--text-muted)]">กำลังตรวจสอบสิทธิ์...</p>;
  }

  if (!canManageLegacyImport(user)) {
    return (
      <div className="surface flex flex-col items-start gap-2 rounded-xl border p-4">
        <p className="text-sm font-medium text-status-repair">คุณไม่มีสิทธิ์เข้าถึงหน้านำเข้าข้อมูลเดิม</p>
        <p className="text-sm text-[var(--text-muted)]">
          ฟีเจอร์นี้จำกัดสิทธิ์เฉพาะผู้ดูแลระบบ กรุณาติดต่อผู้ดูแลระบบหากต้องการเข้าถึง
        </p>
        <Link to="/" className="text-sm text-status-borrowed hover:underline">
          กลับหน้าหลัก
        </Link>
      </div>
    );
  }

  return <>{children}</>;
}
