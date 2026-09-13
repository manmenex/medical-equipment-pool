import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { useAuth } from "@/hooks/useAuth";
import { changePassword } from "@/services/auth";

// Mirrors auth_service.MINIMUM_PASSWORD_LENGTH. The backend remains the
// authority and re-checks everything; this only avoids a round trip to be
// told something the form already knew.
const MINIMUM_PASSWORD_LENGTH = 12;

export function ChangePasswordPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const forced = Boolean(user?.must_change_password);

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);

    // Checked here and nowhere else: the backend never sees the
    // confirmation field, because "you typed it twice" is a property of
    // this form, not of the account.
    if (newPassword !== confirmPassword) {
      setError("รหัสผ่านใหม่และการยืนยันไม่ตรงกัน");
      return;
    }
    if (newPassword.length < MINIMUM_PASSWORD_LENGTH) {
      setError(`รหัสผ่านใหม่ต้องมีอย่างน้อย ${MINIMUM_PASSWORD_LENGTH} ตัวอักษร`);
      return;
    }

    setSubmitting(true);
    try {
      await changePassword(currentPassword, newPassword);
      // The profile carries must_change_password, so it has to be refetched
      // before navigating -- otherwise the guard would bounce the user
      // straight back here on stale data.
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      navigate("/", { replace: true });
    } catch (err) {
      const code = (err as { response?: { data?: { code?: string } } })?.response?.data?.code;
      if (code === "INVALID_CREDENTIALS") {
        setError("รหัสผ่านปัจจุบันไม่ถูกต้อง");
      } else if (code === "SAME_PASSWORD") {
        setError("รหัสผ่านใหม่ต้องไม่ซ้ำกับรหัสผ่านเดิม");
      } else if (code === "WEAK_PASSWORD") {
        setError(`รหัสผ่านใหม่ไม่ผ่านเกณฑ์ ต้องยาวอย่างน้อย ${MINIMUM_PASSWORD_LENGTH} ตัวอักษร และต้องไม่มีช่องว่างนำหน้าหรือต่อท้าย`);
      } else {
        setError("เปลี่ยนรหัสผ่านไม่สำเร็จ กรุณาลองใหม่");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4">
      <h1 className="text-lg font-semibold">เปลี่ยนรหัสผ่าน</h1>

      {forced && (
        <div className="surface rounded-xl border border-status-overdue p-4 text-sm" role="alert">
          <div className="font-medium">ต้องเปลี่ยนรหัสผ่านก่อนใช้งาน</div>
          <p className="mt-1 text-[var(--text-muted)]">
            รหัสผ่านปัจจุบันของคุณถูกตั้งโดยผู้อื่น (รหัสผ่านครั้งแรก หรือผู้ดูแลระบบตั้งให้)
            กรุณาตั้งรหัสผ่านใหม่ที่มีเพียงคุณเท่านั้นที่ทราบ
          </p>
        </div>
      )}

      <form className="surface flex flex-col gap-3 rounded-xl border p-4" onSubmit={onSubmit}>
        <label className="flex flex-col gap-1 text-sm">
          รหัสผ่านปัจจุบัน
          <input
            type="password"
            autoComplete="current-password"
            className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            required
          />
        </label>

        {/* The hint sits OUTSIDE the label deliberately: inside, it becomes
            part of the input's accessible name, so a screen reader reads the
            whole paragraph as the field's label every time it gains focus. */}
        <div className="flex flex-col gap-1">
          <label className="flex flex-col gap-1 text-sm">
            รหัสผ่านใหม่
            <input
              type="password"
              autoComplete="new-password"
              className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
            />
          </label>
          <span className="text-xs text-[var(--text-muted)]">
            อย่างน้อย {MINIMUM_PASSWORD_LENGTH} ตัวอักษร — ความยาวสำคัญกว่าการผสมอักขระพิเศษ
            ประโยคสั้น ๆ ที่คุณจำได้ใช้ได้ดีกว่ารหัสสั้นที่ต้องจดไว้
          </span>
        </div>

        <label className="flex flex-col gap-1 text-sm">
          ยืนยันรหัสผ่านใหม่
          <input
            type="password"
            autoComplete="new-password"
            className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
          />
        </label>

        {error && (
          <div className="text-sm text-status-overdue" role="alert">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="rounded-lg border border-status-borrowed bg-status-borrowed/10 px-3 py-2 text-sm font-medium disabled:opacity-50"
        >
          {submitting ? "กำลังเปลี่ยน..." : "เปลี่ยนรหัสผ่าน"}
        </button>
      </form>
    </div>
  );
}
