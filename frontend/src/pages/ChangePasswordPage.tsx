import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { useAuth } from "@/hooks/useAuth";
import { changePassword } from "@/services/auth";

// Mirrors auth_service.MINIMUM_PASSWORD_LENGTH. The backend remains the
// authority and re-checks everything; this only avoids a round trip to be
// told something the form already knew. If the two ever disagree the backend
// wins and the user sees WEAK_PASSWORD, so the failure mode is a confusing
// message rather than a weak password being accepted.
const MINIMUM_PASSWORD_LENGTH = 6;

// Mirrors password_policy._ALLOWED_PATTERN. Owner decision: English letters
// and digits only. A restriction on the allowed set, NOT a requirement to
// use all three kinds -- "harbour7" is valid.
const ALLOWED_PASSWORD_PATTERN = /^[A-Za-z0-9]+$/;

// Mirrors password_policy: at least one digit (Owner) and, as its necessary
// pair, at least one letter -- without which "123456" satisfies "has a
// digit" while being the most common password in the world.
const HAS_DIGIT = /[0-9]/;
const HAS_LETTER = /[A-Za-z]/;

// Mirrors password_policy.MINIMUM_DISTINCT_CHARACTERS and
// MAXIMUM_SEQUENTIAL_RUN. Only the structural rules are mirrored here, for
// instant feedback. The blocklist and the identifier rule stay server-side:
// shipping the blocklist to the browser would bloat the bundle to restate
// something the server must check anyway, and the identifier rule needs the
// account. Both surface as their own error codes, mapped below.
const MINIMUM_DISTINCT_CHARACTERS = 4;
const MAXIMUM_SEQUENTIAL_RUN = 3;

function hasLongSequentialRun(value: string): boolean {
  let up = 1;
  let down = 1;
  for (let i = 1; i < value.length; i += 1) {
    const step = value.charCodeAt(i) - value.charCodeAt(i - 1);
    up = step === 1 ? up + 1 : 1;
    down = step === -1 ? down + 1 : 1;
    if (Math.max(up, down) > MAXIMUM_SEQUENTIAL_RUN) return true;
  }
  return false;
}

// Mirrors auth_service.MAXIMUM_PASSWORD_BYTES. Not a policy cap: bcrypt
// cannot hash more than 72 bytes. Kept as a byte count because that is what
// bcrypt measures -- with the character rule above the two are identical,
// but this stays correct if the allowed set is ever widened.
const MAXIMUM_PASSWORD_BYTES = 72;

const utf8Bytes = (value: string) => new TextEncoder().encode(value).length;

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
    if (!ALLOWED_PASSWORD_PATTERN.test(newPassword)) {
      setError(
        "รหัสผ่านใหม่ใช้ได้เฉพาะตัวอักษรภาษาอังกฤษ (a-z, A-Z) และตัวเลข (0-9) เท่านั้น " +
          "ห้ามเว้นวรรค อักขระพิเศษ หรือภาษาไทย",
      );
      return;
    }
    if (utf8Bytes(newPassword) > MAXIMUM_PASSWORD_BYTES) {
      setError(`รหัสผ่านใหม่ยาวเกินไป (สูงสุด ${MAXIMUM_PASSWORD_BYTES} ตัวอักษร)`);
      return;
    }
    if (!HAS_DIGIT.test(newPassword)) {
      setError("รหัสผ่านใหม่ต้องมีตัวเลข (0-9) อย่างน้อย 1 ตัว");
      return;
    }
    if (!HAS_LETTER.test(newPassword)) {
      setError("รหัสผ่านใหม่ต้องมีตัวอักษรภาษาอังกฤษอย่างน้อย 1 ตัว");
      return;
    }
    if (new Set(newPassword).size < MINIMUM_DISTINCT_CHARACTERS) {
      setError(
        `รหัสผ่านใหม่ต้องใช้ตัวอักษรที่ไม่ซ้ำกันอย่างน้อย ${MINIMUM_DISTINCT_CHARACTERS} ตัว ` +
          "เช่น 111a11 ใช้ไม่ได้เพราะเดาง่าย",
      );
      return;
    }
    if (hasLongSequentialRun(newPassword)) {
      setError(
        `รหัสผ่านใหม่ต้องไม่มีตัวอักษรเรียงกันเกิน ${MAXIMUM_SEQUENTIAL_RUN} ตัว เช่น 1234 หรือ wxyz`,
      );
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
      } else if (code === "PASSWORD_TOO_COMMON") {
        setError(
          "รหัสผ่านใหม่เป็นรหัสที่คนใช้กันบ่อยเกินไป หรือเป็นรูปแบบที่ดัดแปลงมาเล็กน้อย " +
            "กรุณาเลือกรหัสที่คนอื่นเดา 10 ครั้งแล้วไม่ถูก",
        );
      } else if (code === "PASSWORD_TOO_REPETITIVE") {
        setError("รหัสผ่านใหม่ซ้ำหรือเรียงกันเกินไป จึงเดาได้ง่าย กรุณาเลือกใหม่");
      } else if (code === "PASSWORD_CONTAINS_IDENTIFIER") {
        setError(
          "รหัสผ่านใหม่ต้องไม่มีรหัสพนักงาน ชื่อ หรืออีเมลของคุณอยู่ในนั้น " +
            "เพราะคนที่เห็นบัตรของคุณจะเดาได้ทันที",
        );
      } else if (code === "WEAK_PASSWORD") {
        setError(
          `รหัสผ่านใหม่ไม่ผ่านเกณฑ์ ต้องยาว ${MINIMUM_PASSWORD_LENGTH}-${MAXIMUM_PASSWORD_BYTES} ตัวอักษร ` +
            "และใช้ได้เฉพาะตัวอักษรภาษาอังกฤษกับตัวเลขเท่านั้น",
        );
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
            ใช้ได้เฉพาะ a-z, A-Z และ 0-9 — ยาว {MINIMUM_PASSWORD_LENGTH}-{MAXIMUM_PASSWORD_BYTES} ตัวอักษร
            ต้องมีตัวเลขอย่างน้อย 1 ตัว ไม่บังคับตัวพิมพ์ใหญ่ ห้ามใช้รหัสที่เดาง่าย
            และห้ามมีรหัสพนักงานหรือชื่อของคุณอยู่ในนั้น — ยิ่งยาวยิ่งปลอดภัย
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
