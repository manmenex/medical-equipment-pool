import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { SourceBadge } from "@/components/SourceBadge";
import { StatusBadge } from "@/components/StatusBadge";
import { TransactionCorrectionMenu } from "@/components/TransactionCorrectionMenu";
import { WardCorrectionAction } from "@/components/WardCorrectionAction";
import { apiErrorMessage } from "@/services/api";
import { AddHnAction } from "@/components/entry/AddHnAction";
import { HnReveal } from "@/components/entry/HnField";
import { listTransactions } from "@/services/borrow";
import { canDispatchOrReceiveEquipment, canManageEquipmentMasterData, useAuth } from "@/hooks/useAuth";
import { getEquipment, getEquipmentHistory, returnToOwner } from "@/services/equipment";
import { listWards } from "@/services/masterData";
import type { Shift, TransactionEventBasis, TransactionOut } from "@/types";

// Roadmap PR16 Slice 4 (docs/archive/design/PR16_REPORTING_FOUNDATION_PLAN.md §10):
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
  const { user } = useAuth();
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
  // Roadmap PR16 Slice 4 (docs/archive/design/PR16_REPORTING_FOUNDATION_PLAN.md §10):
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
  // PR61 review fix (H1, merge-blocking): business_date_from/business_date_to/
  // shift are meaningless without a concrete event basis -- the backend has
  // no "all events" value for `event` (Literal["dispatch", "receipt"] =
  // "dispatch"), so omitting it does NOT mean "all events," it silently
  // means "dispatch." "ทั้งหมด" (event = "") must therefore never be
  // combined with business_date_from/business_date_to/shift on the wire --
  // doing so would silently narrow to dispatch-only while the UI claims
  // "all events." This flag is the single authoritative gate, applied at
  // the point requests are actually built (not just on Apply), so it holds
  // regardless of how the URL state was reached (Apply, a shared link,
  // browser navigation).
  const appliedEventIsScoped = appliedEvent !== "";
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
    // PR61 review fix (H1): business_date_from/business_date_to/shift are
    // only ever meaningful together with a concrete event basis. When
    // draftEvent is "" (ทั้งหมด / All), none of the three are sent, even if
    // the controls happen to hold a stale value -- defense in depth on top
    // of these controls being disabled (below) whenever no event is picked.
    const eventIsScoped = draftEvent !== "";
    const from = eventIsScoped ? draftBusinessDateFrom : "";
    const to = eventIsScoped ? draftBusinessDateTo : "";
    const shift = eventIsScoped ? draftShift : "";
    if (from && to && from > to) {
      setBusinessDateRangeError('"วันที่ทำการ ตั้งแต่" ต้องไม่มาหลัง "วันที่ทำการ ถึง"');
      return;
    }
    setBusinessDateRangeError(null);
    const next = new URLSearchParams(searchParams);
    if (from) next.set("business_date_from", from);
    else next.delete("business_date_from");
    if (to) next.set("business_date_to", to);
    else next.delete("business_date_to");
    if (shift) next.set("shift", shift);
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
        business_date_from: appliedEventIsScoped ? appliedBusinessDateFrom || undefined : undefined,
        business_date_to: appliedEventIsScoped ? appliedBusinessDateTo || undefined : undefined,
        shift: appliedEventIsScoped ? appliedShift || undefined : undefined,
        event: appliedEvent || undefined,
        limit: 50,
        cursor: pageParam,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    enabled: Boolean(id),
  });
  const transactions = transactionPages?.pages.flatMap((p) => p.items) ?? [];
  const { data: wards } = useQuery({ queryKey: ["wards"], queryFn: listWards });
  // D28: only the device's latest non-voided transaction is correctable; that is
  // only knowable from the unfiltered list (newest first).
  const unfiltered = !appliedBusinessDateFrom && !appliedBusinessDateTo && !appliedShift && !appliedEvent;
  // TransactionOut carries no created_at (the server picks by created_at, then
  // transaction_no), so the latest EVENT time is the closest client proxy; a
  // backdated entry can still differ, in which case the server's 409
  // CORRECTION_NOT_LATEST is the authority and its message is shown.
  const eventTime = (t: TransactionOut) => new Date(t.returned_at ?? t.borrowed_at).getTime();
  const latestId = unfiltered
    ? [...transactions]
        .filter((t) => t.status !== "voided")
        .sort((a, b) => eventTime(b) - eventTime(a) || b.transaction_no.localeCompare(a.transaction_no))[0]?.id
    : undefined;
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

  function handleCorrectionDone(message: string) {
    setWardCorrectionNotice(message);
    queryClient.invalidateQueries({ queryKey: ["equipment", id] });
    queryClient.invalidateQueries({ queryKey: ["transactions"] });
    queryClient.invalidateQueries({ queryKey: ["active-borrows"] });
  }

  if (isLoading || !equipment) {
    return <p className="text-sm text-[var(--text-muted)]">กำลังโหลด...</p>;
  }

  const isDemoLoan = !!equipment.equipment_source && equipment.equipment_source !== "pool";
  const returned = !!equipment.returned_to_owner_at;
  // Roadmap PR33 (D14): administrator-only "คืนผู้ให้ยืม", only while available at the pool
  // (usability gate; the backend is authoritative).
  const canReturnToOwner =
    canManageEquipmentMasterData(user) && isDemoLoan && !returned && equipment.status === "available_at_pool";

  return (
    <div className="flex flex-col gap-4">
      <div className="surface flex flex-col gap-4 rounded-xl border p-4">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            {equipment.equipment_name}
            <SourceBadge source={equipment.equipment_source} />
          </h1>
          <p className="text-sm text-[var(--text-muted)]">
            {[
              isDemoLoan ? (equipment.bcm_code ? `รหัส ${equipment.bcm_code}` : null) : equipment.asset_number,
              equipment.serial_number ? `SN ${equipment.serial_number}` : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
          <div className="mt-2">
            <StatusBadge status={equipment.status} />
          </div>
          {isDemoLoan && (
            <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm" aria-label="ข้อมูล Demo/ยืม">
              <dt className="text-[var(--text-muted)]">เจ้าของเครื่อง</dt>
              <dd>{equipment.owner_company ?? "-"}</dd>
              <dt className="text-[var(--text-muted)]">กำหนดคืน</dt>
              <dd>{equipment.due_back_date ?? "-"}</dd>
              <dt className="text-[var(--text-muted)]">สายชาร์จ / Clamp</dt>
              <dd>
                {equipment.has_charger === false ? "ไม่มีสายชาร์จ" : "มีสายชาร์จ"} · {equipment.has_clamp === false ? "ไม่มี Clamp" : "มี Clamp"}
              </dd>
              {returned && (
                <>
                  <dt className="text-[var(--text-muted)]">สถานะการยืม</dt>
                  <dd className="text-amber-400">คืนผู้ให้ยืมแล้ว ({new Date(equipment.returned_to_owner_at as string).toLocaleDateString("th-TH")})</dd>
                </>
              )}
            </dl>
          )}
          <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <dt className="text-[var(--text-muted)]">ยี่ห้อ / รุ่น</dt>
            <dd>
              {[equipment.brand, equipment.model].filter(Boolean).join(" ") || "-"}
            </dd>
          </dl>
          <div className="mt-4 flex gap-2">
            {canReturnToOwner && (
              <ReturnToOwnerAction
                equipmentId={equipment.id}
                onDone={() => {
                  queryClient.invalidateQueries({ queryKey: ["equipment"] });
                  queryClient.invalidateQueries({ queryKey: ["dashboard"] });
                }}
              />
            )}
            {equipment.status === "available_at_pool" && !returned && (
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
        <h2 className="mb-3 text-sm font-medium">ประวัติการเบิก-รับคืน</h2>

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
              disabled={draftEvent === ""}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm disabled:opacity-50"
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
              disabled={draftEvent === ""}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm disabled:opacity-50"
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
              disabled={draftEvent === ""}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm disabled:opacity-50"
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
              onChange={(e) => {
                // "ทั้งหมด" has no event basis, so date/shift filters are cleared with it.
                const next = e.target.value as TransactionEventBasis | "";
                setDraftEvent(next);
                if (next === "") {
                  setDraftBusinessDateFrom("");
                  setDraftBusinessDateTo("");
                  setDraftShift("");
                  setBusinessDateRangeError(null);
                }
              }}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm"
            >
              <option value="">ทั้งหมด</option>
              <option value="dispatch">{EVENT_BASIS_LABELS.dispatch}</option>
              <option value="receipt">{EVENT_BASIS_LABELS.receipt}</option>
            </select>
          </div>
        </div>
        {draftEvent === "" && (
          <p className="mb-2 text-xs text-[var(--text-muted)]">เลือก เบิก/รับคืน ก่อนกรองวันที่/กะ</p>
        )}
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
                <li
                  key={tx.id}
                  className={`flex flex-col gap-1 rounded-lg border border-[var(--border)] p-3 text-sm ${tx.status === "voided" ? "opacity-70" : ""}`}
                >
                  <div className={tx.status === "voided" ? "line-through" : ""}>
                    {tx.transaction_no} ·{" "}
                    <strong>
                      {tx.status === "open" ? "อยู่ระหว่างเบิก" : tx.status === "voided" ? "ยกเลิกแล้ว" : "รับคืนแล้ว"}
                    </strong>
                  </div>
                  {tx.status === "voided" && (
                    <div className="text-xs font-medium text-status-repair">
                      ยกเลิกแล้ว{tx.void_reason ? ` · ${tx.void_reason}` : ""}
                    </div>
                  )}
                  {/* Dispatch type/routine round are intentionally not shown: removed by Owner Governance D2
                      (DECISION_LOG 2026-11-25), superseding the PR13 on-demand/routine criterion. */}
                  <div className="text-[var(--text-muted)]">Ward ที่รับ (ณ วันเบิก): {wardName(tx.ward_id)}</div>
                  <div className="text-xs text-[var(--text-muted)]">
                    เบิก {new Date(tx.borrowed_at).toLocaleString("th-TH")}
                    {tx.returned_at ? ` · รับคืน ${new Date(tx.returned_at).toLocaleString("th-TH")}` : ""}
                  </div>
                  {/* Roadmap PR13: a read-only "days since dispatch"
                      indicator replaces the retired overdue-indicator
                      concept -- purely informational, never implies a due
                      date or a maintenance/compliance deadline. */}
                  {tx.status === "open" && (
                    <div className="text-xs text-[var(--text-muted)]">ระยะเวลา {daysSinceDispatch(tx.borrowed_at)} วัน</div>
                  )}
                  {tx.has_hn && <HnReveal transactionId={tx.id} />}
                  {/* Roadmap PR34 (D15): an open dispatch without HN is Standby; staff may add one. */}
                  {tx.status === "open" && !tx.has_hn && canDispatchOrReceiveEquipment(user) && (
                    <div>
                      <AddHnAction
                        transactionId={tx.id}
                        onAdded={() => {
                          void refetchTransactions();
                          void queryClient.invalidateQueries({ queryKey: ["standby-summary"] });
                        }}
                      />
                    </div>
                  )}
                  {tx.id === latestId && (
                    <div className="mt-1">
                      <TransactionCorrectionMenu transaction={tx} onCorrected={handleCorrectionDone} />
                    </div>
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

// Roadmap PR33 (D14): two-step confirm before the administrator marks a demo/loan device as
// returned to its owner (it then leaves active lists/counts/pickers and cannot be dispatched).
function ReturnToOwnerAction({ equipmentId, onDone }: { equipmentId: string; onDone: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await returnToOwner(equipmentId);
      setConfirming(false);
      onDone();
    } catch (err) {
      setError(apiErrorMessage(err, "คืนผู้ให้ยืมไม่สำเร็จ"));
    } finally {
      setBusy(false);
    }
  }

  if (!confirming) {
    return (
      <button
        type="button"
        onClick={() => setConfirming(true)}
        className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium"
      >
        คืนผู้ให้ยืม
      </button>
    );
  }
  return (
    <div role="alertdialog" aria-label="ยืนยันคืนผู้ให้ยืม" className="flex flex-col gap-2 rounded-lg border border-amber-500/60 p-3 text-sm">
      <p>ยืนยันคืนเครื่องนี้ให้ผู้ให้ยืม? เครื่องจะเบิกไม่ได้อีก</p>
      {error && <p role="alert" className="text-status-repair">{error}</p>}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => void confirm()}
          disabled={busy}
          className="rounded-lg bg-status-borrowed px-3 py-1.5 font-medium text-white disabled:opacity-50"
        >
          ยืนยัน
        </button>
        <button type="button" onClick={() => setConfirming(false)} disabled={busy} className="rounded-lg border border-[var(--border)] px-3 py-1.5">
          ยกเลิก
        </button>
      </div>
    </div>
  );
}
