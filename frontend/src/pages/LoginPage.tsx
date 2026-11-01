import axios from "axios";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiErrorCode, apiErrorMessage } from "@/services/api";
import { login } from "@/services/auth";
import type { ApiError } from "@/types";
import { useAuthStore, whenLogoutWipeDone } from "@/store/authStore";

// The backend's own `detail` is English, and the person reading it is a ward
// nurse mid-shift whose password just stopped working. Branching on the
// stable `code` and writing the message in Thai is the difference between "I
// can wait" and a support call. The numbers come from the server
// (error `details`), never hard-coded: lockout is configurable.
export function lockedMessage(details: Record<string, unknown> | undefined): string {
  const maxAttempts = typeof details?.max_attempts === "number" ? details.max_attempts : undefined;
  const lockedUntil = typeof details?.locked_until === "string" ? new Date(details.locked_until) : undefined;
  const validUntil = lockedUntil && !Number.isNaN(lockedUntil.getTime()) ? lockedUntil : undefined;
  const reason = maxAttempts
    ? `เพราะใส่รหัสผ่านผิด ${maxAttempts} ครั้งติดกัน `
    : "เพราะใส่รหัสผ่านผิดหลายครั้งติดกัน ";
  const wait = validUntil
    ? `กรุณารอจนถึงเวลา ${validUntil.toLocaleTimeString("th-TH", {
        timeZone: "Asia/Bangkok",
        hour: "2-digit",
        minute: "2-digit",
      })} น. แล้วลองใหม่ `
    : "กรุณารอสักครู่แล้วลองใหม่ ";
  return (
    `บัญชีนี้ถูกล็อกชั่วคราว ${reason}${wait}` +
    "ถ้าจำรหัสผ่านไม่ได้ ให้ติดต่อผู้ดูแลระบบเพื่อตั้งรหัสใหม่"
  );
}

export function LoginPage() {
  const navigate = useNavigate();
  const setAccessToken = useAuthStore((s) => s.setAccessToken);
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      // PR25E S4: never let a previous logout's wipe run after this login.
      await whenLogoutWipeDone();
      const { access_token } = await login(identifier, password);
      setAccessToken(access_token);
      navigate("/", { replace: true });
    } catch (err) {
      if (apiErrorCode(err) === "ACCOUNT_LOCKED") {
        const data = axios.isAxiosError(err)
          ? (err.response?.data as ApiError | undefined)
          : (err as { response?: { data?: ApiError } })?.response?.data;
        setError(lockedMessage(data?.details));
      } else {
        setError(apiErrorMessage(err, "เข้าสู่ระบบไม่สำเร็จ"));
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={handleSubmit} className="surface w-full max-w-sm rounded-2xl border p-6 shadow-sm">
        <div className="mb-6 text-center">
          <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-status-borrowed text-2xl text-white">
            🏥
          </div>
          <h1 className="text-lg font-semibold">Medical Equipment Pool</h1>
          <p className="text-sm text-[var(--text-muted)]">ระบบรับ-ส่งเครื่องมือแพทย์</p>
        </div>

        {/* htmlFor/id, not decoration: without the association these labels
            are loose text and a screen reader announces two unlabelled text
            fields on the sign-in screen. */}
        <label htmlFor="login-identifier" className="mb-1 block text-sm font-medium">
          รหัสพนักงาน / อีเมล
        </label>
        <input
          id="login-identifier"
          autoFocus
          value={identifier}
          onChange={(e) => setIdentifier(e.target.value)}
          className="mb-4 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 outline-none focus:border-status-borrowed"
          placeholder="ADMIN001"
          required
        />

        <label htmlFor="login-password" className="mb-1 block text-sm font-medium">
          รหัสผ่าน
        </label>
        <div className="mb-4 flex items-center rounded-lg border border-[var(--border)]">
          <input
            id="login-password"
            type={showPassword ? "text" : "password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full bg-transparent px-3 py-2 outline-none"
            required
          />
          <button
            type="button"
            onClick={() => setShowPassword((s) => !s)}
            className="px-3 text-[var(--text-muted)]"
            aria-label="แสดง/ซ่อนรหัสผ่าน"
          >
            {showPassword ? "🙈" : "👁"}
          </button>
        </div>

        {error && <p className="mb-4 text-sm text-status-repair">{error}</p>}

        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-lg bg-status-borrowed py-2.5 font-medium text-white transition hover:opacity-90 disabled:opacity-60"
        >
          {loading ? "กำลังเข้าสู่ระบบ..." : "เข้าสู่ระบบ"}
        </button>
      </form>
    </div>
  );
}
