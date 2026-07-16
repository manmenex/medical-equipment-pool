import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiErrorMessage } from "@/services/api";
import { login } from "@/services/auth";
import { useAuthStore } from "@/store/authStore";

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
      const { access_token } = await login(identifier, password);
      setAccessToken(access_token);
      navigate("/", { replace: true });
    } catch (err) {
      setError(apiErrorMessage(err, "เข้าสู่ระบบไม่สำเร็จ"));
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

        <label className="mb-1 block text-sm font-medium">รหัสพนักงาน / อีเมล</label>
        <input
          autoFocus
          value={identifier}
          onChange={(e) => setIdentifier(e.target.value)}
          className="mb-4 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 outline-none focus:border-status-borrowed"
          placeholder="ADMIN001"
          required
        />

        <label className="mb-1 block text-sm font-medium">รหัสผ่าน</label>
        <div className="mb-4 flex items-center rounded-lg border border-[var(--border)]">
          <input
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
