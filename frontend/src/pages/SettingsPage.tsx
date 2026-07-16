import { roleLabel, useAuth } from "@/hooks/useAuth";
import { applyTheme, useUiStore } from "@/store/uiStore";

export function SettingsPage() {
  const { user } = useAuth();
  const theme = useUiStore((s) => s.theme);
  const setTheme = useUiStore((s) => s.setTheme);

  const changeTheme = (value: "light" | "dark" | "system") => {
    setTheme(value);
    applyTheme(value);
  };

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4">
      <h1 className="text-lg font-semibold">ตั้งค่า</h1>

      <div className="surface rounded-xl border p-4">
        <div className="mb-2 text-sm font-medium">บัญชีผู้ใช้</div>
        <div className="text-sm">{user?.full_name}</div>
        <div className="text-sm text-[var(--text-muted)]">{user ? roleLabel(user.role) : ""}</div>
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

      <div className="surface rounded-xl border p-4 text-sm text-[var(--text-muted)]">
        Medical Equipment Pool v1.0 · Offline-ready PWA
      </div>
    </div>
  );
}
