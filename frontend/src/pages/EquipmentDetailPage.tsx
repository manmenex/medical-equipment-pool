import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { StatusBadge } from "@/components/StatusBadge";
import { getEquipment, getEquipmentHistory } from "@/services/equipment";

export function EquipmentDetailPage() {
  const { id = "" } = useParams();
  const { data: equipment, isLoading } = useQuery({
    queryKey: ["equipment", id],
    queryFn: () => getEquipment(id),
    enabled: Boolean(id),
  });
  const { data: history } = useQuery({
    queryKey: ["equipment", id, "history"],
    queryFn: () => getEquipmentHistory(id),
    enabled: Boolean(id),
  });

  if (isLoading || !equipment) {
    return <p className="text-sm text-[var(--text-muted)]">กำลังโหลด...</p>;
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="surface flex flex-col gap-4 rounded-xl border p-4">
        <div>
          <h1 className="text-lg font-semibold">{equipment.equipment_name}</h1>
          <p className="text-sm text-[var(--text-muted)]">
            {equipment.asset_number}
            {equipment.serial_number ? ` · SN ${equipment.serial_number}` : ""}
          </p>
          <div className="mt-2">
            <StatusBadge status={equipment.status} />
          </div>
          <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <dt className="text-[var(--text-muted)]">ยี่ห้อ / รุ่น</dt>
            <dd>
              {equipment.brand ?? "-"} {equipment.model ?? ""}
            </dd>
            <dt className="text-[var(--text-muted)]">กำหนด PM</dt>
            <dd>{equipment.pm_due_date ?? "-"}</dd>
            <dt className="text-[var(--text-muted)]">กำหนด Calibration</dt>
            <dd>{equipment.cal_due_date ?? "-"}</dd>
          </dl>
          <div className="mt-4 flex gap-2">
            {equipment.status === "available_at_pool" && (
              <Link
                to={`/borrow?equipment_id=${equipment.id}`}
                className="rounded-lg bg-status-borrowed px-4 py-2 text-sm font-medium text-white"
              >
                ยืมเครื่องนี้
              </Link>
            )}
            {equipment.status === "issued_to_ward" && (
              <Link
                to={`/return?equipment_id=${equipment.id}`}
                className="rounded-lg bg-status-available px-4 py-2 text-sm font-medium text-white"
              >
                คืนเครื่องนี้
              </Link>
            )}
          </div>
        </div>
      </div>

      <div className="surface rounded-xl border p-4">
        <h2 className="mb-3 text-sm font-medium">ประวัติการเปลี่ยนสถานะ</h2>
        <ol className="flex flex-col gap-3">
          {(history ?? []).map((h) => (
            <li key={h.id} className="flex items-start gap-3 text-sm">
              <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-status-borrowed" />
              <div>
                <div>
                  {h.from_status ?? "ใหม่"} → <strong>{h.to_status}</strong>
                </div>
                {h.reason && <div className="text-[var(--text-muted)]">{h.reason}</div>}
                <div className="text-xs text-[var(--text-muted)]">{new Date(h.changed_at).toLocaleString("th-TH")}</div>
              </div>
            </li>
          ))}
          {(!history || history.length === 0) && (
            <li className="text-sm text-[var(--text-muted)]">ยังไม่มีประวัติ</li>
          )}
        </ol>
      </div>
    </div>
  );
}
