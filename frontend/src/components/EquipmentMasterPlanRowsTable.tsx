import type { DryRunPlanRowOut } from "@/types/legacyImportApi";

// Roadmap PR20F review round 1 (P1 "Render the ACTUAL DryRunPlan being
// confirmed"): renders the actual persisted plan rows the operator is about
// to confirm/execute -- backend/app/schemas/import_session.py's
// `DryRunPlanRowOut`, exactly as returned, never recomputed. `action` is
// read directly from the backend (CREATE/UPDATE/SKIP); this component never
// infers it from `target_equipment_id` or anything else.
//
// `expected_equipment_version` is intentionally never rendered -- an
// internal optimistic-concurrency value, not something the operator needs
// to review (design says: don't expose Equipment.version unless explicitly
// approved for admin diagnostics).

const NORMALIZED_VALUE_LABELS: Record<string, string> = {
  equipment_name: "ชื่อเครื่องมือ",
  brand: "ยี่ห้อ",
  model: "รุ่น",
  serial_number: "หมายเลขเครื่อง",
  asset_id: "รหัสทรัพย์สิน",
  status: "สถานะ",
};

// bcm_code/item_no are always rendered in their own dedicated columns/
// fields below -- never duplicated inside the generic "normalized values"
// list.
const IDENTITY_KEYS = new Set(["bcm_code", "item_no"]);

const ACTION_LABELS: Record<DryRunPlanRowOut["action"], string> = {
  CREATE: "สร้างใหม่",
  UPDATE: "อัปเดต",
  SKIP: "ข้าม",
};

const ACTION_COLORS: Record<DryRunPlanRowOut["action"], string> = {
  CREATE: "bg-status-available/15 text-status-available",
  UPDATE: "bg-status-borrowed/15 text-status-borrowed",
  SKIP: "bg-[var(--border)]/40 text-[var(--text-muted)]",
};

function ActionBadge({ action }: { action: DryRunPlanRowOut["action"] }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${ACTION_COLORS[action]}`}>
      {ACTION_LABELS[action]}
    </span>
  );
}

function identityValue(row: DryRunPlanRowOut, key: "bcm_code" | "item_no"): string | null {
  const fromIdentity = row.matched_identity_fields?.[key];
  const fromNormalized = row.normalized_values?.[key];
  const value = fromIdentity ?? fromNormalized;
  return typeof value === "string" ? value : null;
}

function normalizedEntries(row: DryRunPlanRowOut): [string, string][] {
  if (!row.normalized_values) return [];
  return Object.entries(row.normalized_values)
    .filter(([key, value]) => !IDENTITY_KEYS.has(key) && value !== null && value !== undefined)
    .map(([key, value]) => [NORMALIZED_VALUE_LABELS[key] ?? key, String(value)]);
}

function warningMessages(row: DryRunPlanRowOut): string[] {
  if (!row.warnings) return [];
  return row.warnings
    .map((w) => (typeof w.message === "string" ? w.message : null))
    .filter((message): message is string => message !== null);
}

export function EquipmentMasterPlanRowsTable({ rows }: { rows: DryRunPlanRowOut[] }) {
  if (rows.length === 0) {
    return <p className="text-sm text-[var(--text-muted)]">ยังไม่มีข้อมูลรายแถวของแผนนี้</p>;
  }

  return (
    <div>
      <div className="hidden overflow-x-auto sm:block">
        <table className="w-full min-w-[820px] text-left text-sm">
          <thead>
            <tr className="border-b border-[var(--border)] text-xs text-[var(--text-muted)]">
              <th scope="col" className="py-2 pr-3 font-medium">
                แถว
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                การดำเนินการ
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                BCM
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                Item No.
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                อ้างอิงเครื่องมือ
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                ค่าที่จะบันทึก
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                คำเตือน
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const warnings = warningMessages(row);
              return (
                <tr key={row.id} className="border-b border-[var(--border)] align-top last:border-0">
                  <td className="py-2 pr-3">{row.source_row_number}</td>
                  <td className="py-2 pr-3">
                    <ActionBadge action={row.action} />
                  </td>
                  <td className="py-2 pr-3">{identityValue(row, "bcm_code") ?? "-"}</td>
                  <td className="py-2 pr-3">{identityValue(row, "item_no") ?? "-"}</td>
                  <td className="py-2 pr-3">{row.target_equipment_id ?? "-"}</td>
                  <td className="py-2 pr-3 text-[var(--text-muted)]">
                    {normalizedEntries(row).length > 0 ? (
                      <ul className="flex flex-col gap-0.5">
                        {normalizedEntries(row).map(([label, value]) => (
                          <li key={label}>
                            {label}: {value}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      "-"
                    )}
                  </td>
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
          const bcm = identityValue(row, "bcm_code");
          const itemNo = identityValue(row, "item_no");
          return (
            <li key={row.id} className="surface rounded-xl border p-3 text-sm">
              <div className="mb-1 flex items-center justify-between gap-2">
                <span className="font-medium">แถว {row.source_row_number}</span>
                <ActionBadge action={row.action} />
              </div>
              {(bcm || itemNo) && (
                <p className="text-[var(--text-muted)]">
                  {bcm && `BCM: ${bcm}`}
                  {bcm && itemNo && " · "}
                  {itemNo && `Item No.: ${itemNo}`}
                </p>
              )}
              {row.target_equipment_id && (
                <p className="mt-1 break-all text-xs text-[var(--text-muted)]">อ้างอิงเครื่องมือ: {row.target_equipment_id}</p>
              )}
              {normalizedEntries(row).length > 0 && (
                <ul className="mt-1 flex flex-col gap-0.5">
                  {normalizedEntries(row).map(([label, value]) => (
                    <li key={label}>
                      {label}: {value}
                    </li>
                  ))}
                </ul>
              )}
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
