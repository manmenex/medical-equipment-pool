import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { STATUS_LABELS } from "@/components/StatusBadge";
import { listCategories, listDepartments } from "@/services/masterData";
import type { EquipmentStatus } from "@/types";

// Roadmap PR17 Slice 4 (docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md §9/
// §10.3): the Equipment Verify Checklist's own, distinct approved filter
// set -- equipment category, current status, and department. Deliberately
// NOT the Receive/Issue reports' ReportFilterBar (business date/shift/
// ward/equipment/operator) -- this report has no date/shift basis and no
// Ward relationship (§7.3(A)/§10.3's corrected query param set); reusing
// that component here would silently add filters this report does not
// support. Category/department selects reuse the exact same
// listCategories/listDepartments services and select-element pattern
// ReportFilterBar already established, avoiding duplicate fetch/render
// logic for those two lookups specifically.
export function EquipmentVerifyChecklistFilterBar() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [draftCategoryId, setDraftCategoryId] = useState(searchParams.get("equipment_category_id") ?? "");
  const [draftStatus, setDraftStatus] = useState<EquipmentStatus | "">(
    (searchParams.get("status") as EquipmentStatus | null) ?? ""
  );
  const [draftDepartmentId, setDraftDepartmentId] = useState(searchParams.get("department_id") ?? "");

  const { data: categories } = useQuery({ queryKey: ["categories"], queryFn: listCategories });
  const { data: departments } = useQuery({ queryKey: ["departments"], queryFn: listDepartments });

  function apply() {
    const next = new URLSearchParams(searchParams);
    const setOrDelete = (key: string, value: string) => (value ? next.set(key, value) : next.delete(key));
    setOrDelete("equipment_category_id", draftCategoryId);
    setOrDelete("status", draftStatus);
    setOrDelete("department_id", draftDepartmentId);
    setSearchParams(next);
  }

  function clear() {
    setDraftCategoryId("");
    setDraftStatus("");
    setDraftDepartmentId("");
    const next = new URLSearchParams(searchParams);
    for (const key of ["equipment_category_id", "status", "department_id"]) {
      next.delete(key);
    }
    setSearchParams(next);
  }

  return (
    <div className="surface mb-3 rounded-xl border p-4">
      <h2 className="mb-3 text-sm font-medium">ตัวกรอง</h2>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div>
          <label htmlFor="verify-checklist-filter-category" className="mb-1 block text-xs text-[var(--text-muted)]">
            หมวดหมู่เครื่องมือ
          </label>
          <select
            id="verify-checklist-filter-category"
            value={draftCategoryId}
            onChange={(e) => setDraftCategoryId(e.target.value)}
            className="w-full rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm"
          >
            <option value="">ทั้งหมด</option>
            {(categories ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="verify-checklist-filter-status" className="mb-1 block text-xs text-[var(--text-muted)]">
            สถานะ
          </label>
          <select
            id="verify-checklist-filter-status"
            value={draftStatus}
            onChange={(e) => setDraftStatus(e.target.value as EquipmentStatus | "")}
            className="w-full rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm"
          >
            <option value="">ทั้งหมด</option>
            {(Object.keys(STATUS_LABELS) as EquipmentStatus[]).map((status) => (
              <option key={status} value={status}>
                {STATUS_LABELS[status]}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="verify-checklist-filter-department" className="mb-1 block text-xs text-[var(--text-muted)]">
            หน่วยงานเจ้าของ
          </label>
          <select
            id="verify-checklist-filter-department"
            value={draftDepartmentId}
            onChange={(e) => setDraftDepartmentId(e.target.value)}
            className="w-full rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm"
          >
            <option value="">ทั้งหมด</option>
            {(departments ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={apply}
          className="rounded-lg bg-status-borrowed px-4 py-2 text-sm font-medium text-white"
        >
          นำตัวกรองไปใช้
        </button>
        <button
          type="button"
          onClick={clear}
          className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium"
        >
          ล้างตัวกรอง
        </button>
      </div>
    </div>
  );
}
