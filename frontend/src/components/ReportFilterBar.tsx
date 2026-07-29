import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { OperatorAutocomplete } from "@/components/OperatorAutocomplete";
import { listCategories, listWards } from "@/services/masterData";
import type { ReportOperatorOut, Shift } from "@/types";

const SHIFT_LABELS: Record<Shift, string> = {
  day: "กลางวัน",
  night: "กลางคืน",
};

// Roadmap PR17 Slice 3 (docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md §9/§12):
// the approved filter set, shared verbatim by ReceiveReportPage and
// IssueReportPage so the two screens never duplicate this UI or its
// apply/clear behavior. URL search params are the single source of truth
// for the *applied* filter values (same useSearchParams pattern already
// established by EquipmentDetailPage.tsx) -- a page refresh or shared link
// reproduces the exact same filtered view. Draft values are only sent to
// the API once "นำตัวกรองไปใช้" (Apply) is pressed.
//
// Known limitation, accepted rather than engineered around: a URL that
// already carries `operator_id` (e.g. a shared link) restores the applied
// filter correctly, but the OperatorAutocomplete's own text box cannot
// resolve that id back into a display_name without a second lookup
// endpoint this design does not add -- it starts empty until the operator
// is re-selected, even though the filter itself is still applied and sent.
export function ReportFilterBar() {
  const [searchParams, setSearchParams] = useSearchParams();
  const appliedBusinessDateFrom = searchParams.get("business_date_from") ?? "";
  const appliedBusinessDateTo = searchParams.get("business_date_to") ?? "";

  const [draftBusinessDateFrom, setDraftBusinessDateFrom] = useState(appliedBusinessDateFrom);
  const [draftBusinessDateTo, setDraftBusinessDateTo] = useState(appliedBusinessDateTo);
  const [draftShift, setDraftShift] = useState<Shift | "">((searchParams.get("shift") as Shift | null) ?? "");
  const [draftWardId, setDraftWardId] = useState(searchParams.get("ward_id") ?? "");
  const [draftCategoryId, setDraftCategoryId] = useState(searchParams.get("equipment_category_id") ?? "");
  const [draftEquipmentId, setDraftEquipmentId] = useState(searchParams.get("equipment_id") ?? "");
  const [draftOperator, setDraftOperator] = useState<ReportOperatorOut | null>(null);
  const [rangeError, setRangeError] = useState<string | null>(null);

  const { data: wards } = useQuery({ queryKey: ["wards"], queryFn: listWards });
  const { data: categories } = useQuery({ queryKey: ["categories"], queryFn: listCategories });

  function apply() {
    if (draftBusinessDateFrom && draftBusinessDateTo && draftBusinessDateFrom > draftBusinessDateTo) {
      setRangeError('"วันที่ทำการ ตั้งแต่" ต้องไม่มาหลัง "วันที่ทำการ ถึง"');
      return;
    }
    setRangeError(null);
    const next = new URLSearchParams(searchParams);
    const setOrDelete = (key: string, value: string) => (value ? next.set(key, value) : next.delete(key));
    setOrDelete("business_date_from", draftBusinessDateFrom);
    setOrDelete("business_date_to", draftBusinessDateTo);
    setOrDelete("shift", draftShift);
    setOrDelete("ward_id", draftWardId);
    setOrDelete("equipment_category_id", draftCategoryId);
    setOrDelete("equipment_id", draftEquipmentId);
    setOrDelete("operator_id", draftOperator?.id ?? "");
    setSearchParams(next);
  }

  function clear() {
    setDraftBusinessDateFrom("");
    setDraftBusinessDateTo("");
    setDraftShift("");
    setDraftWardId("");
    setDraftCategoryId("");
    setDraftEquipmentId("");
    setDraftOperator(null);
    setRangeError(null);
    const next = new URLSearchParams(searchParams);
    for (const key of [
      "business_date_from",
      "business_date_to",
      "shift",
      "ward_id",
      "equipment_category_id",
      "equipment_id",
      "operator_id",
    ]) {
      next.delete(key);
    }
    setSearchParams(next);
  }

  return (
    <div className="surface mb-3 rounded-xl border p-4">
      <h2 className="mb-3 text-sm font-medium">ตัวกรอง</h2>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div>
          <label htmlFor="report-filter-business-date-from" className="mb-1 block text-xs text-[var(--text-muted)]">
            วันที่ทำการ ตั้งแต่
          </label>
          <input
            id="report-filter-business-date-from"
            type="date"
            value={draftBusinessDateFrom}
            onChange={(e) => setDraftBusinessDateFrom(e.target.value)}
            className="w-full rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm"
          />
        </div>
        <div>
          <label htmlFor="report-filter-business-date-to" className="mb-1 block text-xs text-[var(--text-muted)]">
            วันที่ทำการ ถึง
          </label>
          <input
            id="report-filter-business-date-to"
            type="date"
            value={draftBusinessDateTo}
            onChange={(e) => setDraftBusinessDateTo(e.target.value)}
            className="w-full rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm"
          />
        </div>
        <div>
          <label htmlFor="report-filter-shift" className="mb-1 block text-xs text-[var(--text-muted)]">
            กะ
          </label>
          <select
            id="report-filter-shift"
            value={draftShift}
            onChange={(e) => setDraftShift(e.target.value as Shift | "")}
            className="w-full rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm"
          >
            <option value="">ทั้งหมด</option>
            <option value="day">{SHIFT_LABELS.day}</option>
            <option value="night">{SHIFT_LABELS.night}</option>
          </select>
        </div>
        <div>
          <label htmlFor="report-filter-ward" className="mb-1 block text-xs text-[var(--text-muted)]">
            หอผู้ป่วย
          </label>
          <select
            id="report-filter-ward"
            value={draftWardId}
            onChange={(e) => setDraftWardId(e.target.value)}
            className="w-full rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm"
          >
            <option value="">ทั้งหมด</option>
            {(wards ?? []).map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="report-filter-category" className="mb-1 block text-xs text-[var(--text-muted)]">
            หมวดหมู่เครื่องมือ
          </label>
          <select
            id="report-filter-category"
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
          <label htmlFor="report-filter-equipment-id" className="mb-1 block text-xs text-[var(--text-muted)]">
            รหัสเครื่องมือ (UUID)
          </label>
          <input
            id="report-filter-equipment-id"
            type="text"
            value={draftEquipmentId}
            onChange={(e) => setDraftEquipmentId(e.target.value)}
            placeholder="เว้นว่างไว้เพื่อดูทั้งหมด"
            className="w-full rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm"
          />
        </div>
        <div className="col-span-2">
          <OperatorAutocomplete id="report-filter-operator" value={draftOperator} onChange={setDraftOperator} />
        </div>
      </div>
      {rangeError && <p className="mt-2 text-xs text-status-repair">{rangeError}</p>}
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
