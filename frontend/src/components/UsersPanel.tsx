import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { roleLabel } from "@/hooks/useAuth";
import { apiErrorMessage } from "@/services/api";
import { createUser, listUsers, resetUserPassword, updateUser } from "@/services/users";
import type { ManagedUser, PasswordResetResult } from "@/services/users";
import type { Role } from "@/types";

const ROLES: Role[] = ["administrator", "equipment_pool_staff", "read_only"];
const INPUT = "rounded-lg border border-[var(--border)] bg-transparent px-3 py-2";

export function UsersPanel({ currentUserId }: { currentUserId?: string }) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["users"], queryFn: listUsers });
  const [error, setError] = useState<string | null>(null);
  const [confirmUser, setConfirmUser] = useState<ManagedUser | null>(null);
  // Held only in component state while the dialog is open; cleared on close.
  const [tempResult, setTempResult] = useState<PasswordResetResult | null>(null);
  const [copied, setCopied] = useState(false);

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["users"] });

  const patchMutation = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: { role_name?: Role; is_active?: boolean } }) =>
      updateUser(id, patch),
    onSuccess: () => {
      setError(null);
      return refresh();
    },
    onError: (err) => setError(apiErrorMessage(err, "อัปเดตผู้ใช้ไม่สำเร็จ")),
  });

  const resetMutation = useMutation({
    mutationFn: (id: string) => resetUserPassword(id),
    onSuccess: (result) => {
      setError(null);
      setConfirmUser(null);
      setCopied(false);
      setTempResult(result);
    },
    onError: (err) => {
      setConfirmUser(null);
      setError(apiErrorMessage(err, "รีเซ็ตรหัสผ่านไม่สำเร็จ"));
    },
  });

  const copyPassword = async () => {
    if (!tempResult) return;
    try {
      await navigator.clipboard.writeText(tempResult.temporary_password);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  const closeTemp = () => {
    setTempResult(null);
    setCopied(false);
  };

  return (
    <div className="flex flex-col gap-4">
      <CreateUserForm onCreated={refresh} />
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}
      {isLoading ? (
        <p className="text-sm">กำลังโหลด...</p>
      ) : (
        <div className="surface overflow-x-auto rounded-xl border">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b">
                <th className="p-2">รหัสพนักงาน</th>
                <th className="p-2">ชื่อ</th>
                <th className="p-2">อีเมล</th>
                <th className="p-2">ระดับสิทธิ์</th>
                <th className="p-2">สถานะ</th>
                <th className="p-2">การดำเนินการ</th>
              </tr>
            </thead>
            <tbody>
              {(data ?? []).map((u) => {
                const isSelf = u.id === currentUserId;
                return (
                  <tr key={u.id} className="border-b last:border-0">
                    <td className="p-2">{u.employee_code}</td>
                    <td className="p-2">{u.full_name}</td>
                    <td className="p-2">{u.email}</td>
                    <td className="p-2">
                      <select
                        aria-label={`ระดับสิทธิ์ ${u.employee_code}`}
                        value={u.role}
                        disabled={isSelf || patchMutation.isPending}
                        onChange={(e) => patchMutation.mutate({ id: u.id, patch: { role_name: e.target.value as Role } })}
                        className={INPUT}
                      >
                        {ROLES.map((r) => (
                          <option key={r} value={r}>
                            {roleLabel(r)}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="p-2">{u.is_active ? "ใช้งาน" : "ปิดใช้งาน"}</td>
                    <td className="flex flex-wrap gap-2 p-2">
                      <button
                        disabled={isSelf || patchMutation.isPending}
                        onClick={() => patchMutation.mutate({ id: u.id, patch: { is_active: !u.is_active } })}
                        className="surface rounded-lg border px-2 py-1 disabled:opacity-50"
                        aria-label={`${u.is_active ? "ปิดใช้งาน" : "เปิดใช้งาน"} ${u.employee_code}`}
                      >
                        {u.is_active ? "ปิดใช้งาน" : "เปิดใช้งาน"}
                      </button>
                      <button
                        disabled={isSelf}
                        onClick={() => setConfirmUser(u)}
                        className="surface rounded-lg border px-2 py-1 disabled:opacity-50"
                        aria-label={`รีเซ็ตรหัสผ่าน ${u.employee_code}`}
                      >
                        รีเซ็ตรหัสผ่าน
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {confirmUser && (
        <div role="dialog" aria-modal="true" aria-label="ยืนยันการรีเซ็ตรหัสผ่าน" className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="surface flex max-w-sm flex-col gap-3 rounded-xl border p-4">
            <p>
              ต้องการรีเซ็ตรหัสผ่านของ {confirmUser.employee_code} ({confirmUser.full_name}) หรือไม่? รหัสผ่านเดิมจะใช้ไม่ได้ทันที
            </p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setConfirmUser(null)} className="surface rounded-lg border px-3 py-1.5">
                ยกเลิก
              </button>
              <button
                onClick={() => resetMutation.mutate(confirmUser.id)}
                disabled={resetMutation.isPending}
                className="rounded-lg bg-status-borrowed px-3 py-1.5 text-white"
              >
                ยืนยัน
              </button>
            </div>
          </div>
        </div>
      )}

      {tempResult && (
        <div role="dialog" aria-modal="true" aria-label="รหัสผ่านชั่วคราว" className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="surface flex max-w-sm flex-col gap-3 rounded-xl border p-4">
            <p>รหัสผ่านชั่วคราวของ {tempResult.employee_code}</p>
            <code data-testid="temp-password" className="break-all rounded border p-2 font-mono">
              {tempResult.temporary_password}
            </code>
            <p role="note" className="text-sm font-medium text-red-600">
              รหัสผ่านนี้จะแสดงเพียงครั้งเดียว กรุณาคัดลอกและส่งให้ผู้ใช้ ผู้ใช้ต้องเปลี่ยนรหัสผ่านเมื่อเข้าสู่ระบบครั้งถัดไป
            </p>
            <div className="flex justify-end gap-2">
              <button onClick={copyPassword} className="surface rounded-lg border px-3 py-1.5">
                {copied ? "คัดลอกแล้ว" : "คัดลอก"}
              </button>
              <button onClick={closeTemp} className="rounded-lg bg-status-borrowed px-3 py-1.5 text-white">
                ปิด
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function CreateUserForm({ onCreated }: { onCreated: () => void }) {
  const [employeeCode, setEmployeeCode] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("read_only");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: (input: Parameters<typeof createUser>[0]) => createUser(input),
    onSuccess: (created) => {
      setMessage(`เพิ่มผู้ใช้ ${created.employee_code} สำเร็จ`);
      setError(null);
      setEmployeeCode("");
      setFullName("");
      setEmail("");
      setPassword("");
      setRole("read_only");
      onCreated();
    },
    onError: (err) => {
      setMessage(null);
      setError(apiErrorMessage(err, "เพิ่มผู้ใช้ไม่สำเร็จ"));
    },
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate({
          employee_code: employeeCode.trim(),
          full_name: fullName.trim(),
          email: email.trim(),
          password,
          role_name: role,
        });
      }}
      className="surface flex max-w-md flex-col gap-3 rounded-xl border p-4"
    >
      <input required aria-label="รหัสพนักงาน" placeholder="รหัสพนักงาน" value={employeeCode} onChange={(e) => setEmployeeCode(e.target.value)} className={INPUT} />
      <input required aria-label="ชื่อ-นามสกุล" placeholder="ชื่อ-นามสกุล" value={fullName} onChange={(e) => setFullName(e.target.value)} className={INPUT} />
      <input required type="email" aria-label="อีเมล" placeholder="อีเมล" value={email} onChange={(e) => setEmail(e.target.value)} className={INPUT} />
      <input required type="password" autoComplete="new-password" aria-label="รหัสผ่านเริ่มต้น" placeholder="รหัสผ่านเริ่มต้น" value={password} onChange={(e) => setPassword(e.target.value)} className={INPUT} />
      <select aria-label="ระดับสิทธิ์ผู้ใช้ใหม่" value={role} onChange={(e) => setRole(e.target.value as Role)} className={INPUT}>
        {ROLES.map((r) => (
          <option key={r} value={r}>
            {roleLabel(r)}
          </option>
        ))}
      </select>
      <button type="submit" disabled={mutation.isPending} className="rounded-lg bg-status-borrowed px-3 py-2 text-white">
        เพิ่มผู้ใช้
      </button>
      {message && <p className="text-sm text-green-700">{message}</p>}
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}
    </form>
  );
}
