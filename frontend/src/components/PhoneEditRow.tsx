import { useState } from "react";

import { apiErrorMessage } from "@/services/api";

// Roadmap PR25E slice S0: inline phone view/edit for one ward/department.
// Rendered with an edit control only when `canEdit` (administrator); the
// backend PATCH remains the authority.
export function PhoneEditRow({
  label,
  phone,
  canEdit,
  onSave,
}: {
  label: string;
  phone: string | null | undefined;
  canEdit: boolean;
  onSave: (phone: string | null) => Promise<unknown>;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(phone ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSave(value.trim() === "" ? null : value.trim());
      setEditing(false);
    } catch (err) {
      setError(apiErrorMessage(err, "บันทึกเบอร์โทรไม่สำเร็จ"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <li className="px-4 py-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="flex-1">{label}</span>
        {!editing && (
          <>
            <span className="text-[var(--text-muted)]">เบอร์โทร: {phone || "-"}</span>
            {canEdit && (
              <button
                type="button"
                onClick={() => {
                  setValue(phone ?? "");
                  setEditing(true);
                }}
                className="surface rounded-lg border px-2 py-1 text-xs"
              >
                แก้ไขเบอร์โทร
              </button>
            )}
          </>
        )}
      </div>
      {editing && (
        <form onSubmit={save} className="mt-2 flex flex-wrap items-center gap-2">
          <input
            aria-label="เบอร์โทร"
            maxLength={20}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-1.5"
          />
          <button
            type="submit"
            disabled={saving}
            className="rounded-lg bg-status-borrowed px-3 py-1.5 text-xs font-medium text-white disabled:opacity-60"
          >
            {saving ? "กำลังบันทึก..." : "บันทึก"}
          </button>
          <button type="button" onClick={() => setEditing(false)} className="text-xs">
            ยกเลิก
          </button>
        </form>
      )}
      {error && <p className="mt-1 text-xs text-status-repair">{error}</p>}
    </li>
  );
}
