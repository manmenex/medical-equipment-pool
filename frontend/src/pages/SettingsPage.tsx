import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import {
  canManageEquipmentMasterData,
  canManageLegacyImport,
  canReviewCutoverReadiness,
  canReviewReconciliation,
  canReviewSyncConflicts,
  roleLabel,
  useAuth,
} from "@/hooks/useAuth";
import { fetchSyncConflicts } from "@/services/syncReview";
import { applyTheme, useUiStore } from "@/store/uiStore";

type HubCard = { to: string; icon: string; title: string; description: string; badge?: number };

function HubCardLink({ card }: { card: HubCard }) {
  return (
    <Link
      to={card.to}
      className="surface flex flex-col gap-1 rounded-xl border p-3 hover:bg-black/5 dark:hover:bg-white/5"
    >
      <div className="text-sm font-medium">
        <span className="mr-2">{card.icon}</span>
        {card.title}
        {card.badge ? (
          <span
            aria-label={`รอตรวจสอบ ${card.badge} รายการ`}
            className="ml-2 rounded-full bg-status-repair px-2 py-0.5 text-xs text-white"
          >
            {card.badge}
          </span>
        ) : null}
      </div>
      <div className="text-xs text-[var(--text-muted)]">{card.description}</div>
    </Link>
  );
}

export function SettingsPage() {
  const { user } = useAuth();
  const theme = useUiStore((s) => s.theme);
  const setTheme = useUiStore((s) => s.setTheme);

  // Same role gates as the former sidebar entries (usability only; the
  // backend stays the authority).
  const reviewAllowed = canReviewSyncConflicts(user);
  const reviewCount = useQuery({
    queryKey: ["sync-conflicts-count"],
    queryFn: () => fetchSyncConflicts({ limit: 1 }),
    enabled: reviewAllowed,
    refetchInterval: 60_000,
    retry: false,
  }).data?.total;

  const dataCards: HubCard[] = [
    ...(canManageEquipmentMasterData(user)
      ? [
          {
            to: "/admin",
            icon: "⚙️",
            title: "จัดการระบบ",
            description: "เครื่องมือ, เครื่อง Demo/ยืม, แผนก, หอผู้ป่วย, สถานที่, หมวดหมู่, นำเข้าคลังเครื่องมือและเบอร์โทรหอผู้ป่วย, ผู้ใช้",
          },
        ]
      : []),
    ...(canManageLegacyImport(user)
      ? [{ to: "/imports", icon: "📥", title: "นำเข้าข้อมูลเดิม", description: "นำเข้าข้อมูลจากระบบเดิม" }]
      : []),
    ...(reviewAllowed
      ? [
          {
            to: "/sync-review",
            icon: "📨",
            title: "ตรวจสอบรายการออฟไลน์",
            description: "ตรวจสอบรายการที่บันทึกแบบออฟไลน์แล้วซิงก์ไม่สำเร็จ",
            badge: reviewCount,
          },
        ]
      : []),
  ];

  const migrationCards: HubCard[] = [
    ...(canReviewReconciliation(user)
      ? [
          {
            to: "/reconciliation",
            icon: "🔎",
            title: "ตรวจสอบข้อมูลย้อนหลัง",
            description: "เทียบข้อมูลที่นำเข้าจากระบบเดิมกับข้อมูลในระบบนี้ หาจุดที่ไม่ตรงกัน",
          },
        ]
      : []),
    ...(canReviewCutoverReadiness(user)
      ? [
          {
            to: "/cutover-readiness",
            icon: "🚦",
            title: "ความพร้อมก่อนเปลี่ยนระบบ",
            description: "เช็กลิสต์ว่าระบบพร้อมเลิกใช้ระบบเดิมหรือยัง",
          },
        ]
      : []),
  ];

  const changeTheme = (value: "light" | "dark" | "system") => {
    setTheme(value);
    applyTheme(value);
  };

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      <h1 className="text-lg font-semibold">ตั้งค่า</h1>

      <div className="surface rounded-xl border p-4">
        <div className="mb-2 text-sm font-medium">บัญชีผู้ใช้</div>
        <div className="text-sm">{user?.full_name}</div>
        <div className="text-sm text-[var(--text-muted)]">{user ? roleLabel(user.role) : ""}</div>
        <Link
          to="/change-password"
          className="mt-3 inline-block rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm"
        >
          เปลี่ยนรหัสผ่าน
        </Link>
      </div>

      <div className="surface rounded-xl border p-4">
        <div className="mb-2 text-sm font-medium">ธีม</div>
        <div className="flex gap-2">
          {(["light", "dark", "system"] as const).map((t) => (
            <button
              key={t}
              onClick={() => changeTheme(t)}
              className={`rounded-lg border px-3 py-1.5 text-sm ${
                theme === t ? "border-status-borrowed bg-status-borrowed/10" : "border-[var(--border)]"
              }`}
            >
              {t === "light" ? "สว่าง" : t === "dark" ? "มืด" : "ตามระบบ"}
            </button>
          ))}
        </div>
      </div>

      {dataCards.length > 0 && (
        <section aria-labelledby="data-mgmt-heading" className="flex flex-col gap-2">
          <h2 id="data-mgmt-heading" className="text-sm font-medium">
            การจัดการข้อมูล
          </h2>
          <div className="grid gap-2 sm:grid-cols-2">
            {dataCards.map((c) => (
              <HubCardLink key={c.to} card={c} />
            ))}
          </div>
        </section>
      )}

      {migrationCards.length > 0 && (
        <section aria-labelledby="migration-heading" className="flex flex-col gap-2">
          <h2 id="migration-heading" className="text-sm font-medium">
            การย้ายระบบ (ใช้ช่วงเปลี่ยนจาก AppSheet)
          </h2>
          <div className="grid gap-2 sm:grid-cols-2">
            {migrationCards.map((c) => (
              <HubCardLink key={c.to} card={c} />
            ))}
          </div>
        </section>
      )}

      <div className="surface rounded-xl border p-4 text-sm text-[var(--text-muted)]">
        Medical Equipment Pool v1.0 · Offline-ready PWA
      </div>
    </div>
  );
}
