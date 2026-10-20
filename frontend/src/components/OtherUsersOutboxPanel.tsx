import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import { useOfflineMode } from "@/hooks/useOfflineMode";
import { canReviewSyncConflicts, useAuth } from "@/hooks/useAuth";
import {
  adoptOps,
  listAdoptableGroups,
  reauthenticate,
  type AdoptableGroup,
  type AdoptSummary,
} from "@/offline/adoption";
import { apiErrorMessage } from "@/services/api";
import { opTypeLabel } from "@/utils/syncReviewLabels";

// PR25E S5b (design 8.3): shown only to pool staff / administrators, only when
// this device's outbox holds ops of users other than the logged-in one.
// Nothing is pre-selected or sent automatically.

function fmt(iso: string | null): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "-" : d.toLocaleString("th-TH");
}

export function OtherUsersOutboxPanel() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const offline = useOfflineMode();
  const allowed = canReviewSyncConflicts(user);
  const [groups, setGroups] = useState<AdoptableGroup[]>([]);
  const [target, setTarget] = useState<AdoptableGroup | null>(null);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<AdoptSummary | null>(null);

  const userId = user ? String(user.id) : null;
  const load = useCallback(async () => {
    if (!userId || !allowed) return;
    try {
      setGroups(await listAdoptableGroups(userId));
    } catch {
      setGroups([]);
    }
  }, [userId, allowed]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!allowed || (groups.length === 0 && !summary)) return null;

  const close = () => {
    setTarget(null);
    setPassword("");
    setError(null);
  };

  const confirm = async () => {
    if (!target || !userId || busy || !password) return;
    setBusy(true);
    setError(null);
    try {
      try {
        await reauthenticate(password);
      } catch (e) {
        setError(apiErrorMessage(e) || "รหัสผ่านไม่ถูกต้อง");
        return;
      }
      setPassword("");
      const result = await adoptOps(userId, new Set([target.user_id]));
      setSummary(result);
      close();
      await load();
      await qc.invalidateQueries({ queryKey: ["sync-conflicts"] });
      await qc.invalidateQueries({ queryKey: ["sync-conflicts-count"] });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="surface space-y-3 rounded-xl border p-3 text-sm" aria-label="รายการค้างของผู้ใช้อื่น">
      <h2 className="font-semibold">รายการค้างของผู้ใช้อื่น</h2>
      {groups.length > 0 && (
        <p className="text-[var(--text-muted)]">
          เครื่องนี้มีรายการที่ผู้ใช้อื่นบันทึกไว้แต่ยังไม่ได้ส่ง คุณสามารถส่งแทนได้ ผู้บันทึกเดิมยังคงเป็นผู้บันทึกรายการ
          และชื่อของคุณจะถูกบันทึกเป็นผู้ส่ง
        </p>
      )}
      <ul className="space-y-2">
        {groups.map((g) => (
          <li key={g.user_id} className="flex flex-wrap items-center justify-between gap-2" data-testid="other-user-group">
            <span>
              {g.name ?? "ผู้ใช้ไม่ทราบชื่อ"} — {g.count} รายการ
              <span className="block text-xs text-[var(--text-muted)]">
                {g.ops
                  .slice(0, 5)
                  .map((o) => `${opTypeLabel(o.op_type)} ${o.bcm_code ?? "-"} ${fmt(o.occurred_at)}`)
                  .join(" · ")}
                {g.ops.length > 5 ? " ..." : ""}
              </span>
            </span>
            <button
              className="rounded-lg bg-status-borrowed px-3 py-1 text-white disabled:opacity-50"
              disabled={busy || offline}
              onClick={() => setTarget(g)}
            >
              ส่งแทน
            </button>
          </li>
        ))}
      </ul>
      {offline && groups.length > 0 && <p className="text-status-repair">ต้องออนไลน์จึงจะส่งแทนได้</p>}

      {summary && (
        <div role="status" className="space-y-1 rounded-lg bg-black/5 p-2" data-testid="adopt-summary">
          <p>
            ส่งสำเร็จ {summary.applied + summary.duplicate} รายการ
            {summary.conflict > 0 && ` · ต้องตรวจสอบ ${summary.conflict} รายการ (ดูในรายการด้านล่าง)`}
            {summary.rejected > 0 && ` · ถูกปฏิเสธ ${summary.rejected} รายการ`}
            {summary.left_pending > 0 && ` · ยังค้างอยู่ ${summary.left_pending} รายการ`}
          </p>
          {summary.reauth_required && <p className="text-status-repair">ต้องยืนยันรหัสผ่านอีกครั้งก่อนส่งแทน</p>}
          {summary.error && <p className="text-status-repair">ส่งไม่สำเร็จ ({summary.error}) รายการยังอยู่ในเครื่อง</p>}
        </div>
      )}

      {target && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="ยืนยันการส่งแทน"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
        >
          <div className="surface w-full max-w-md space-y-3 rounded-xl border p-4">
            <h3 className="font-semibold">ส่งแทน</h3>
            <p>
              คุณกำลังส่ง {target.count} รายการที่บันทึกโดย {target.name ?? "ผู้ใช้ไม่ทราบชื่อ"} รายการจะยังบันทึกในชื่อผู้บันทึกเดิม
              และชื่อของคุณจะถูกบันทึกเป็นผู้ส่ง
            </p>
            <label className="block">
              ยืนยันรหัสผ่านของคุณ
              <input
                type="password"
                autoComplete="current-password"
                className="mt-1 w-full rounded-lg border p-2"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            {error && (
              <p role="alert" className="text-status-repair">
                {error}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <button className="rounded-lg border px-3 py-1" disabled={busy} onClick={close}>
                ยกเลิก
              </button>
              <button
                className="rounded-lg bg-status-borrowed px-3 py-1 text-white disabled:opacity-50"
                disabled={busy || !password}
                onClick={() => void confirm()}
              >
                {busy ? "กำลังส่ง..." : "ยืนยันและส่ง"}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
