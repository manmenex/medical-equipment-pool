import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { StatusBadge } from "@/components/StatusBadge";
import { WardCorrectionAction } from "@/components/WardCorrectionAction";
import { listTransactions } from "@/services/borrow";
import { getEquipment, getEquipmentHistory } from "@/services/equipment";
import { listWards } from "@/services/masterData";
import type { TransactionOut } from "@/types";

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
  // Roadmap PR9B review round 2 (Codex incremental review, PR34-R2-M2): a
  // single limit:50 page silently hid every CLOSED transaction beyond the
  // first page for equipment with a long history, and had no distinct
  // loading/error state -- a failed fetch rendered identically to a
  // genuinely empty history. useInfiniteQuery follows the backend's own
  // next_cursor (services/borrow.ts's listTransactions, unchanged
  // contract) through an explicit "โหลดเพิ่มเติม" action instead of
  // discarding it, and isLoading/isError below are read and rendered
  // distinctly from an empty result.
  const transactionsQueryKey = ["equipment", id, "transactions"];
  const {
    data: transactionPages,
    isLoading: transactionsLoading,
    isError: transactionsError,
    refetch: refetchTransactions,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: transactionsQueryKey,
    queryFn: ({ pageParam }) => listTransactions({ equipment_id: id, limit: 50, cursor: pageParam }),
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
    queryClient.invalidateQueries({ queryKey: transactionsQueryKey });
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

      {wardCorrectionNotice && <p className="text-sm text-status-available">{wardCorrectionNotice}</p>}

      <div className="surface rounded-xl border p-4">
        <h2 className="mb-3 text-sm font-medium">ประวัติการยืม-คืน</h2>
        {transactionsLoading && (
          <p className="text-sm text-[var(--text-muted)]">กำลังโหลดประวัติการยืม-คืน...</p>
        )}
        {transactionsError && (
          <div className="flex flex-col items-start gap-2">
            <p className="text-sm text-status-repair">ไม่สามารถโหลดประวัติการยืม-คืนได้</p>
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
                    <strong>{tx.status === "open" ? "อยู่ระหว่างยืม" : "คืนแล้ว"}</strong>
                  </div>
                  <div className="text-[var(--text-muted)]">แผนก: {wardName(tx.ward_id)}</div>
                  <div className="text-xs text-[var(--text-muted)]">
                    ยืมเมื่อ {new Date(tx.borrowed_at).toLocaleString("th-TH")}
                    {tx.returned_at ? ` · คืนเมื่อ ${new Date(tx.returned_at).toLocaleString("th-TH")}` : ""}
                  </div>
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
                <li className="text-sm text-[var(--text-muted)]">ยังไม่มีประวัติการยืม-คืน</li>
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
