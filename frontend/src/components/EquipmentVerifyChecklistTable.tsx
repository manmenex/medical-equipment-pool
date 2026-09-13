import { useQuery } from "@tanstack/react-query";

import { StatusBadge } from "@/components/StatusBadge";
import { listCategories, listDepartments } from "@/services/masterData";
import type { Equipment } from "@/types";

// Roadmap PR17 Slice 4 (docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md
// §7.3(A)/§8): renders exactly what the backend returns -- a current-state
// listing of Equipment rows. No lifecycle/eligibility logic, no client-side
// sort, no field derivation of any kind; category/department names are
// resolved for display only, from the same cached lookups the filter bar
// already uses.
export function EquipmentVerifyChecklistTable({ rows }: { rows: Equipment[] }) {
  const { data: categories } = useQuery({ queryKey: ["categories"], queryFn: listCategories });
  const { data: departments } = useQuery({ queryKey: ["departments"], queryFn: listDepartments });

  function categoryName(categoryId: string | null): string {
    if (!categoryId) return "-";
    return categories?.find((c) => c.id === categoryId)?.name ?? "-";
  }

  function departmentName(departmentId: string | null): string {
    if (!departmentId) return "-";
    return departments?.find((d) => d.id === departmentId)?.name ?? "-";
  }

  if (rows.length === 0) {
    return <p className="text-sm text-[var(--text-muted)]">ไม่พบรายการ</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-left text-sm">
        <thead>
          <tr className="border-b border-[var(--border)] text-xs text-[var(--text-muted)]">
            <th scope="col" className="py-2 pr-3 font-medium">
              เครื่องมือ
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              รหัสครุภัณฑ์
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              หมวดหมู่
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              หน่วยงานเจ้าของ
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              สถานะ
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-b border-[var(--border)] last:border-0">
              <td className="py-2 pr-3">
                {row.equipment_name}
                {row.bcm_code && <div className="text-xs text-[var(--text-muted)]">{row.bcm_code}</div>}
              </td>
              <td className="py-2 pr-3">
                {row.asset_number}
                {row.serial_number && <div className="text-xs text-[var(--text-muted)]">SN {row.serial_number}</div>}
              </td>
              <td className="py-2 pr-3">{categoryName(row.category_id)}</td>
              <td className="py-2 pr-3">{departmentName(row.department_owner_id)}</td>
              <td className="py-2 pr-3">
                <StatusBadge status={row.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
