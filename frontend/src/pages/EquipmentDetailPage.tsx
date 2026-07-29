import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { StatusBadge } from "@/components/StatusBadge";
import { WardCorrectionAction } from "@/components/WardCorrectionAction";
import { apiErrorMessage } from "@/services/api";
import { listTransactions } from "@/services/borrow";
import { getEquipment, getEquipmentHistory } from "@/services/equipment";
import { listWards } from "@/services/masterData";
import type { DispatchType, RoutineRound, Shift, TransactionEventBasis, TransactionOut } from "@/types";

// Roadmap PR13 (docs/audits/04-consolidated-implementation-plan.md's PR13
// entry, Part H acceptance criterion "when viewed in history, [an
// on-demand dispatch] is distinguishable from routine dispatches"):
// reuses BorrowPage.tsx's own dispatch-type/round labels so the two
// screens describe the same concept identically.
const DISPATCH_TYPE_LABELS: Record<DispatchType, string> = {
  on_demand: "เบิกตามคำขอ (On-Demand)",
  routine_round: "รอบเวลาปกติ (Routine Round)",
};

const ROUTINE_ROUNDS: RoutineRound[] = ["06:00", "11:00", "15:00", "21:00"];

// Roadmap PR16 Slice 4 (docs/design/PR16_REPORTING_FOUNDATION_PLAN.md §10):
// ค่ากะ -- กลางวัน / กลางคืน, matching the design's own Thai wording.
const SHIFT_LABELS: Record<Shift, string> = {
  day: "กลางวัน",
  night: "กลางคืน",
};

// เบิก/รับคืน already used verbatim on this page and BorrowPage/ReturnPage
// for the dispatch/receipt actions -- reused here for the event basis
// selector so the same domain term always reads the same way.
const EVENT_BASIS_LABELS: Record<TransactionEventBasis, string> = {
  dispatch: "เบิก",
  receipt: "รับคืน",
};

function daysSinceDispatch(borrowedAt: string): number {
  const borrowed = new Date(borrowedAt).getTime();
  const elapsedMs = Date.now() - borrowed;
  return Math.max(0, Math.floor(elapsedMs / (1000 * 60 * 60 * 24)));
}

// Roadmap PR9B review round 2 (Finding 3): getEquipmentHistory's
// EquipmentStatusHistoryItem rows (from_status/to_status/reason) are
// equipment lifecycle-state transitions, not transactions -- they carry no
// transaction ID and cannot substitute for one. GET /transactions with
// equipment_id (already used elsewhere via services/borrow.ts's
// listTransactions) is the actual transaction record source, with real
// TransactionOut.id values for both OPEN and CLOSED transactions -- the
// backend's ward-correction endpoint intentionally has no lifecycle-status
// precondition (docs/api/transactions.md), so a CLOSED transaction (e.g. an
// error discovered after the equipment was already received back into the
// pool) must remain correctable from here.
export function EquipmentDetailPage() {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
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
  // Roadmap PR13: dispatch-type/round-aware and date-range history
  // filtering, on top of the equipment_id scope this page already applies.
  // All optional and independently combinable (backend/app/crud/transaction.py's
  // search()).
  const [dispatchTypeFilter, setDispatchTypeFilter] = useState<DispatchType | "">("");
  const [routineRoundFilter, setRoutineRoundFilter] = useState<RoutineRound | "">("");
  const [fromDateFilter, setFromDateFilter] = useState("");
  const [toDateFilter, setToDateFilter] = useState("");

  // Roadmap PR16 Slice 4 (docs/design/PR16_REPORTING_FOUNDATION_PLAN.md §10):
  // business_date_from/business_date_to/shift/event -- a distinct filter
  // basis from the from_date/to_date raw-timestamp pair above, never merged
  // with or substituted for it (see the design's explicit correction on
  // this point). URL search params are the single source of truth for the
  // *applied* filter values (same useSearchParams pattern already
  // established by EquipmentListPage.tsx), so a page refresh or shared link
  // reproduces the exact same filtered view; the four draft* fields below
  // are only the uncommitted form state the pickers/selects are bound to
  // until "Apply Filters" is pressed.
  const [searchParams, setSearchParams] = useSearchParams();
  const appliedBusinessDateFrom = searchParams.get("business_date_from") ?? "";
  const appliedBusinessDateTo = searchParams.get("business_date_to") ?? "";
  const appliedShift = (searchParams.get("shift") as Shift | null) ?? "";
  const appliedEvent = (searchParams.get("event") as TransactionEventBasis | null) ?? "";
  const [draftBusinessDateFrom, setDraftBusinessDateFrom] = useState(appliedBusinessDateFrom);
  const [draftBusinessDateTo, setDraftBusinessDateTo] = useState(appliedBusinessDateTo);
  const [draftShift, setDraftShift] = useState<Shift | "">(appliedShift);
  const [draftEvent, setDraftEvent] = useState<TransactionEventBasis | "">(appliedEvent);
  // Frontend validation is limited to the one "obvious UI mistake" the
  // design calls out (from > to) -- everything else (an unrecognized shift/
  // event value, etc.) is left to the backend's own validation, surfaced via
  // apiErrorMessage(transactionsErrorObj) below, never re-implemented here.
  const [businessDateRangeError, setBusinessDateRangeError] = useState<string | null>(null);

  function applyBusinessDateFilters() {
    if (draftBusinessDateFrom && draftBusinessDateTo && draftBusinessDateFrom > draftBusinessDateTo) {
      setBusinessDateRangeError('"วันที่ทำการ ตั้งแต่" ต้องไม่มาหลัง "วันที่ทำการ ถึง"');
      return;
    }
    setBusinessDateRangeError(null);
    const next = new URLSearchParams(searchParams);
    if (draftBusinessDateFrom) next.set("business_date_from", draftBusinessDateFrom);
    else next.delete("business_date_from");
    if (draftBusinessDateTo) next.set("business_date_to", draftBusinessDateTo);
    else next.delete("business_date_to");
    if (draftShift) next.set("shift", draftShift);
    else next.delete("shift");
    if (draftEvent) next.set("event", draftEvent);
    else next.delete("event");
    setSearchParams(next);
  }

  function clearBusinessDateFilters() {
    setDraftBusinessDateFrom("");
    setDraftBusinessDateTo("");
    setDraftShift("");
    setDraftEvent("");
    setBusinessDateRangeError(null);
    const next = new URLSearchParams(searchParams);
    next.delete("business_date_from");
    next.delete("business_date_to");
    next.delete("shift");
    next.delete("event");
    setSearchParams(next);
  }
  // Roadmap PR9B review round 2 (Codex incremental review, PR34-R2-M2): a
  // single limit:50 page silently hid every CLOSED transaction beyond the
  // first page for equipment with a long history, and had no distinct
  // loading/error state -- a failed fetch rendered identically to a
  // genuinely empty history. useInfiniteQuery follows the backend's own
  // next_cursor (services/borrow.ts's listTransactions, unchanged
  // contract) through an explicit "โหลดเพิ่มเติม" action instead of
  // discarding it, and isLoading/isError below are read and rendered
  // distinctly from an empty result.
  const transactionsQueryKey = [
    "equipment",
    id,
    "transactions",
    dispatchTypeFilter,
    routineRoundFilter,
    fromDateFilter,
    toDateFilter,
    appliedBusinessDateFrom,
    appliedBusinessDateTo,
    appliedShift,
    appliedEvent,
  ];
  const {
    data: transactionPages,
    isLoading: transactionsLoading,
    isError: transactionsError,
    error: transactionsErrorObj,
    refetch: refetchTransactions,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: transactionsQueryKey,
    queryFn: ({ pageParam }) =>
      listTransactions({
        equipment_id: id,
        dispatch_type: dispatchTypeFilter || undefined,
        routine_round: routineRoundFilter || undefined,
        business_date_from: appliedBusinessDateFrom || undefined,
        business_date_to: appliedBusinessDateTo || undefined,
        shift: appliedShift || undefined,
        event: appliedEvent || undefined,
        from_date: fromDateFilter || undefined,
        to_date: toDateFilter || undefined,
        limit: 50,
        cursor: pageParam,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    enabled: Boolean(id),
  });
  const transactions = transactionPages?.pages.flatMap((p) => p.items) ?? [];
  const { data: wards } = useQuery({ queryKey: ["wards"], queryFn: listWards });
  const [wardCorrectionNotice, setWardCorrectionNotice] = useState<string | null>(null);

  function wardName(wardId: string | null): string {
    if (!wardId) return "ไม่ทราบ";
    return wards?.find((w) => w.id === wardId)?.name ?? "ไม่ทราบ";
  }

  function handleWardCorrected(_updated: TransactionOut, message: string) {
    setWardCorrectionNotice(message);
    // Roadmap PR9B review round 2: narrow, entity-scoped invalidation --
    // this equipment's own transaction history is the list that displays
    // the corrected ward, so it is refetched; the generic transactions
    // namespace is also invalidated in case another screen (e.g.
    // ReturnPage) has this same transaction cached. Equipment queries are
    // deliberately not invalidated -- ward correction never changes
    // equipment status or any equipment-detail field.
    // Roadmap PR13: invalidate by the ["equipment", id, "transactions"]
    // prefix, not the full filtered transactionsQueryKey -- the key now
    // carries the active filter values, and every filter combination this
    // equipment's history has been fetched under must be refetched, not
    // just the one currently selected.
    queryClient.invalidateQueries({ queryKey: ["equipment", id, "transactions"] });
    queryClient.invalidateQueries({ queryKey: ["transactions"] });
  }

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
                เบิกเครื่องนี้
              </Link>
            )}
            {equipment.status === "issued_to_ward" && (
              <Link
                to={`/return?equipment_id=${equipment.id}`}
                className="rounded-lg bg-status-available px-4 py-2 text-sm font-medium text-white"
              >
                รับคืนเครื่องนี้
              </Link>
            )}
          </div>
        </div>
      </div>

      {wardCorrectionNotice && <p className="text-sm text-status-available">{wardCorrectionNotice}</p>}

      <div className="surface rounded-xl border p-4">
        <h2 className="mb-1 text-sm font-medium">ประวัติการเบิก-รับคืน</h2>
        {/* Workflow Audit §7.1: this is the detail-view caption -- the ward
            shown per transaction below is a one-time record of where the
            equipment was first sent, never a live tracker of its later
            movement between wards. */}
        <p className="mb-3 text-xs text-[var(--text-muted)]">
          หอผู้ป่วยที่แสดงคือหอผู้ป่วยที่รับเครื่อง ณ วันที่เบิกเท่านั้น ระบบไม่ได้ติดตามการเคลื่อนย้ายเครื่องมือในภายหลัง
        </p>

        {/* Roadmap PR13: dispatch-type/round-aware and date-range history
            filtering (docs/audits/04-consolidated-implementation-plan.md's
            PR13 entry). All four filters are optional and independently
            combinable; changing any of them refetches from the first page. */}
        <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div>
            <label htmlFor="tx-filter-dispatch-type" className="mb-1 block text-xs text-[var(--text-muted)]">
              ประเภทการเบิก
            </label>
            <select
              id="tx-filter-dispatch-type"
              value={dispatchTypeFilter}
              onChange={(e) => {
                const next = e.target.value as DispatchType | "";
                setDispatchTypeFilter(next);
                if (next !== "routine_round") setRoutineRoundFilter("");
              }}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm"
            >
              <option value="">ทั้งหมด</option>
              <option value="on_demand">{DISPATCH_TYPE_LABELS.on_demand}</option>
              <option value="routine_round">{DISPATCH_TYPE_LABELS.routine_round}</option>
            </select>
          </div>
          <div>
            <label htmlFor="tx-filter-routine-round" className="mb-1 block text-xs text-[var(--text-muted)]">
              รอบเวลา
            </label>
            <select
              id="tx-filter-routine-round"
              value={routineRoundFilter}
              onChange={(e) => setRoutineRoundFilter(e.target.value as RoutineRound | "")}
              disabled={dispatchTypeFilter !== "routine_round"}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm disabled:opacity-50"
            >
              <option value="">ทั้งหมด</option>
              {ROUTINE_ROUNDS.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="tx-filter-from-date" className="mb-1 block text-xs text-[var(--text-muted)]">
              ตั้งแต่วันที่
            </label>
            <input
              id="tx-filter-from-date"
              type="date"
              value={fromDateFilter}
              onChange={(e) => setFromDateFilter(e.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm"
            />
          </div>
          <div>
            <label htmlFor="tx-filter-to-date" className="mb-1 block text-xs text-[var(--text-muted)]">
              ถึงวันที่
            </label>
            <input
              id="tx-filter-to-date"
              type="date"
              value={toDateFilter}
              onChange={(e) => setToDateFilter(e.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm"
            />
          </div>
        </div>

        {/* Roadmap PR16 Slice 4 (docs/design/PR16_REPORTING_FOUNDATION_PLAN.md
            §10): business_date_from/business_date_to/shift/event -- kept as
            an explicitly separate control group from the from_date/to_date
            pair above (never merged, never relabeled), since the two
            represent genuinely different concepts: raw event timestamp vs.
            backend-derived Asia/Bangkok business day/shift. Draft values are
            only sent to the API once "นำตัวกรองไปใช้" (Apply) is pressed;
            business_date/shift are never computed here, only selected. */}
        <div className="mb-1 flex items-baseline justify-between gap-2">
          <h3 className="text-xs font-medium text-[var(--text-muted)]">ตัวกรองตามวันที่ทำการและกะ</h3>
        </div>
        <p className="mb-2 text-xs text-[var(--text-muted)]">
          วันที่ทำการและกะคำนวณโดยระบบตามเวลาประเทศไทย แยกจาก &quot;ตั้งแต่วันที่ / ถึงวันที่&quot; ด้านบนซึ่งกรองตามเวลาที่บันทึกจริง
        </p>
        <div className="mb-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div>
            <label htmlFor="tx-filter-business-date-from" className="mb-1 block text-xs text-[var(--text-muted)]">
              วันที่ทำการ ตั้งแต่
            </label>
            <input
              id="tx-filter-business-date-from"
              type="date"
              value={draftBusinessDateFrom}
              onChange={(e) => setDraftBusinessDateFrom(e.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm"
            />
          </div>
          <div>
            <label htmlFor="tx-filter-business-date-to" className="mb-1 block text-xs text-[var(--text-muted)]">
              วันที่ทำการ ถึง
            </label>
            <input
              id="tx-filter-business-date-to"
              type="date"
              value={draftBusinessDateTo}
              onChange={(e) => setDraftBusinessDateTo(e.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm"
            />
          </div>
          <div>
            <label htmlFor="tx-filter-shift" className="mb-1 block text-xs text-[var(--text-muted)]">
              กะ
            </label>
            <select
              id="tx-filter-shift"
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
            <label htmlFor="tx-filter-event" className="mb-1 block text-xs text-[var(--text-muted)]">
              เหตุการณ์
            </label>
            <select
              id="tx-filter-event"
              value={draftEvent}
              onChange={(e) => setDraftEvent(e.target.value as TransactionEventBasis | "")}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm"
            >
              <option value="">ทั้งหมด</option>
              <option value="dispatch">{EVENT_BASIS_LABELS.dispatch}</option>
              <option value="receipt">{EVENT_BASIS_LABELS.receipt}</option>
            </select>
          </div>
        </div>
        {businessDateRangeError && <p className="mb-2 text-xs text-status-repair">{businessDateRangeError}</p>}
        <div className="mb-3 flex gap-2">
          <button
            type="button"
            onClick={applyBusinessDateFilters}
            className="rounded-lg bg-status-borrowed px-4 py-2 text-sm font-medium text-white"
          >
            นำตัวกรองไปใช้
          </button>
          <button
            type="button"
            onClick={clearBusinessDateFilters}
            className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium"
          >
            ล้างตัวกรอง
          </button>
        </div>

        {transactionsLoading && (
          <p className="text-sm text-[var(--text-muted)]">กำลังโหลดประวัติการเบิก-รับคืน...</p>
        )}
        {transactionsError && (
          <div className="flex flex-col items-start gap-2">
            <p className="text-sm text-status-repair">
              {apiErrorMessage(transactionsErrorObj, "ไม่สามารถโหลดประวัติการเบิก-รับคืนได้")}
            </p>
            <button
              type="button"
              onClick={() => refetchTransactions()}
              className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
            >
              ลองใหม่
            </button>
          </div>
        )}
        {!transactionsLoading && !transactionsError && (
          <>
            <ol className="flex flex-col gap-3">
              {transactions.map((tx) => (
                <li key={tx.id} className="flex flex-col gap-1 rounded-lg border border-[var(--border)] p-3 text-sm">
                  <div>
                    เลขที่รายการ {tx.transaction_no} ·{" "}
                    <strong>{tx.status === "open" ? "อยู่ระหว่างเบิก" : "รับคืนแล้ว"}</strong>
                  </div>
                  {/* Roadmap PR13 (Part H acceptance criterion): an
                      on-demand dispatch must be distinguishable from a
                      routine-round dispatch when viewed in history. */}
                  <div className="text-[var(--text-muted)]">
                    {tx.dispatch_type ? DISPATCH_TYPE_LABELS[tx.dispatch_type] : "ไม่ระบุประเภทการเบิก"}
                    {tx.dispatch_type === "routine_round" && tx.routine_round ? ` · รอบ ${tx.routine_round}` : ""}
                  </div>
                  <div className="text-[var(--text-muted)]">
                    หอผู้ป่วยที่รับเครื่อง (บันทึก ณ วันที่เบิก): {wardName(tx.ward_id)}
                  </div>
                  <div className="text-xs text-[var(--text-muted)]">
                    เบิกเมื่อ {new Date(tx.borrowed_at).toLocaleString("th-TH")}
                    {tx.returned_at ? ` · รับคืนเมื่อ ${new Date(tx.returned_at).toLocaleString("th-TH")}` : ""}
                  </div>
                  {/* Roadmap PR13: a read-only "days since dispatch"
                      indicator replaces the retired overdue-indicator
                      concept -- purely informational, never implies a due
                      date or a maintenance/compliance deadline. */}
                  {tx.status === "open" && (
                    <div className="text-xs text-[var(--text-muted)]">เบิกมาแล้ว {daysSinceDispatch(tx.borrowed_at)} วัน</div>
                  )}
                  <div className="mt-1">
                    <WardCorrectionAction
                      transaction={tx}
                      onCorrected={handleWardCorrected}
                      triggerClassName="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium disabled:opacity-60"
                    />
                  </div>
                </li>
              ))}
              {transactions.length === 0 && (
                <li className="text-sm text-[var(--text-muted)]">ยังไม่มีประวัติการเบิก-รับคืน</li>
              )}
            </ol>
            {hasNextPage && (
              <button
                type="button"
                onClick={() => fetchNextPage()}
                disabled={isFetchingNextPage}
                className="mt-3 w-full rounded-lg border border-[var(--border)] py-2.5 text-sm font-medium disabled:opacity-60"
              >
                {isFetchingNextPage ? "กำลังโหลด..." : "โหลดเพิ่มเติม"}
              </button>
            )}
          </>
        )}
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
