import type { LegacyHistoryDryRunPlanRowOut } from "@/types/legacyImportApi";
import { formatDateTimeInTimezone } from "@/utils/printFormat";

// Roadmap PR21E (design §14/§18/§19): renders the actual persisted PR21
// plan rows the operator is about to confirm/execute --
// backend/app/schemas/legacy_history_import.py's
// LegacyHistoryDryRunPlanRowOut, exactly as returned, never recomputed or
// paired here. `event_type` is read directly from the backend
// (ISSUE/RECEIVE); this component never infers pairing, Ward resolution,
// or BME provenance. Fields shown are exactly what the backend's own
// `normalized_values` ever writes (see that schema's own docstring) --
// never a notes/หมายเหตุ field or raw JSON, since none exists on this
// contract.

const EVENT_TYPE_LABELS: Record<LegacyHistoryDryRunPlanRowOut["event_type"], string> = {
  ISSUE: "ส่งเครื่อง",
  RECEIVE: "รับเครื่อง",
};

const EVENT_TYPE_COLORS: Record<LegacyHistoryDryRunPlanRowOut["event_type"], string> = {
  ISSUE: "bg-status-borrowed/15 text-status-borrowed",
  RECEIVE: "bg-status-available/15 text-status-available",
};

function EventTypeBadge({ eventType }: { eventType: LegacyHistoryDryRunPlanRowOut["event_type"] }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${EVENT_TYPE_COLORS[eventType]}`}
    >
      {EVENT_TYPE_LABELS[eventType]}
    </span>
  );
}

function warningMessages(row: LegacyHistoryDryRunPlanRowOut): string[] {
  return row.warnings ?? [];
}

export function LegacyHistoryPlanRowsTable({ rows }: { rows: LegacyHistoryDryRunPlanRowOut[] }) {
  if (rows.length === 0) {
    return <p className="text-sm text-[var(--text-muted)]">ยังไม่มีข้อมูลรายแถวของแผนนี้</p>;
  }

  return (
    <div>
      <div className="hidden overflow-x-auto sm:block">
        <table className="w-full min-w-[900px] text-left text-sm">
          <thead>
            <tr className="border-b border-[var(--border)] text-xs text-[var(--text-muted)]">
              <th scope="col" className="py-2 pr-3 font-medium">
                แถว
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                ประเภท
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                วันเวลา
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                เลขอ้างอิงเดิม
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                เครื่องมือ
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                หอผู้ป่วยเดิม
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                BME เดิม
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                คำเตือน
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const warnings = warningMessages(row);
              const v = row.values;
              return (
                <tr key={row.id} className="border-b border-[var(--border)] align-top last:border-0">
                  <td className="py-2 pr-3">{row.source_row_number}</td>
                  <td className="py-2 pr-3">
                    <EventTypeBadge eventType={row.event_type} />
                  </td>
                  <td className="py-2 pr-3">{v ? formatDateTimeInTimezone(v.occurred_at, "Asia/Bangkok") : "-"}</td>
                  <td className="py-2 pr-3">{v?.legacy_order_reference ?? "-"}</td>
                  <td className="py-2 pr-3 break-all">{v?.equipment_id ?? "-"}</td>
                  <td className="py-2 pr-3">
                    {v?.legacy_ward_text ?? "-"}
                    {v?.resolved_ward_id && (
                      <p className="mt-0.5 break-all text-xs text-[var(--text-muted)]">
                        อ้างอิงหอผู้ป่วย: {v.resolved_ward_id}
                      </p>
                    )}
                  </td>
                  <td className="py-2 pr-3">{v?.legacy_bme_name ?? "-"}</td>
                  <td className="py-2 pr-3">
                    {warnings.length > 0 ? (
                      <ul className="flex flex-col gap-0.5 text-status-pm">
                        {warnings.map((message, index) => (
                          // eslint-disable-next-line react/no-array-index-key -- warnings have no stable id in this contract
                          <li key={index}>{message}</li>
                        ))}
                      </ul>
                    ) : (
                      <span className="text-[var(--text-muted)]">-</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <ul className="flex flex-col gap-2 sm:hidden">
        {rows.map((row) => {
          const warnings = warningMessages(row);
          const v = row.values;
          return (
            <li key={row.id} className="surface rounded-xl border p-3 text-sm">
              <div className="mb-1 flex items-center justify-between gap-2">
                <span className="font-medium">แถว {row.source_row_number}</span>
                <EventTypeBadge eventType={row.event_type} />
              </div>
              {v && <p className="text-[var(--text-muted)]">{formatDateTimeInTimezone(v.occurred_at, "Asia/Bangkok")}</p>}
              {v?.legacy_order_reference && <p className="mt-1">เลขอ้างอิงเดิม: {v.legacy_order_reference}</p>}
              {v?.equipment_id && <p className="mt-1 break-all text-xs text-[var(--text-muted)]">เครื่องมือ: {v.equipment_id}</p>}
              {v?.legacy_ward_text && <p className="mt-1">หอผู้ป่วยเดิม: {v.legacy_ward_text}</p>}
              {v?.legacy_bme_name && <p className="mt-1">BME เดิม: {v.legacy_bme_name}</p>}
              {warnings.length > 0 && (
                <ul className="mt-1 flex flex-col gap-0.5 text-status-pm">
                  {warnings.map((message, index) => (
                    // eslint-disable-next-line react/no-array-index-key -- warnings have no stable id in this contract
                    <li key={index}>{message}</li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
