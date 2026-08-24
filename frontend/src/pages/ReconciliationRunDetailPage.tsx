import { useEffect, useRef, useState } from "react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { ReconciliationDispositionDialog } from "@/components/ReconciliationDispositionDialog";
import { ReconciliationSignOffDialog } from "@/components/ReconciliationSignOffDialog";
import { canSetReconciliationDisposition, canSignOffReconciliation, useAuth } from "@/hooks/useAuth";
import { apiErrorCode, apiErrorMessage } from "@/services/api";
import {
  fetchReconciliationFinding,
  fetchReconciliationFindings,
  fetchReconciliationRun,
  fetchReconciliationSignoff,
  reconciliationKeys,
} from "@/services/reconciliation";
import type { ReconciliationDisposition, ReconciliationFindingDetail, ReconciliationSeverity } from "@/types/reconciliation";
import { formatDateTimeInTimezone } from "@/utils/printFormat";
import {
  RECONCILIATION_DISPOSITION_COLORS,
  RECONCILIATION_DISPOSITION_FILTER_LABELS,
  RECONCILIATION_DISPOSITION_LABELS,
  RECONCILIATION_RUN_STATUS_COLORS,
  RECONCILIATION_RUN_STATUS_LABELS,
  RECONCILIATION_SEVERITY_COLORS,
  RECONCILIATION_SEVERITY_LABELS,
  reconciliationFindingCodeLabel,
} from "@/utils/reconciliationLabels";

const SEVERITY_FILTER_OPTIONS: ReconciliationSeverity[] = ["high", "medium", "low"];
const DISPOSITION_FILTER_OPTIONS: Array<"open" | ReconciliationDisposition> = [
  "open",
  "confirmed_valid",
  "confirmed_duplicate",
  "accepted_unresolved",
  "requires_correction",
];

// Roadmap PR22F -- the primary reconciliation review screen (backend:
// PR22D's run/finding read+disposition endpoints, PR22E's sign-off
// endpoints). Every mutation here (disposition, sign-off) only ever
// submits a request and reacts to the backend's response -- see the
// dialog components this page renders for the actual submit/error
// handling; this page owns query state, filters, and which dialog (if
// any) is open.
export function ReconciliationRunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const { user } = useAuth();
  const queryClient = useQueryClient();

  const [severityFilter, setSeverityFilter] = useState<ReconciliationSeverity | "">("");
  const [dispositionFilter, setDispositionFilter] = useState<"open" | ReconciliationDisposition | "">("");
  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(null);
  const [dispositionTarget, setDispositionTarget] = useState<string | null>(null);
  const [signOffDialogOpen, setSignOffDialogOpen] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const findingTriggerRef = useRef<HTMLButtonElement | null>(null);
  const signOffTriggerRef = useRef<HTMLButtonElement | null>(null);

  const runQuery = useQuery({
    queryKey: reconciliationKeys.run(runId ?? ""),
    queryFn: () => fetchReconciliationRun(runId as string),
    enabled: Boolean(runId),
  });

  // GET .../sign-off's 404 (RECONCILIATION_SIGNOFF_NOT_FOUND) is the
  // normal "not yet signed off" state, not a query failure (§24 of the
  // task) -- resolved to `null` here so the page can render the unsigned
  // state without a red error panel.
  const signoffQuery = useQuery({
    queryKey: reconciliationKeys.signoff(runId ?? ""),
    queryFn: async () => {
      try {
        return await fetchReconciliationSignoff(runId as string);
      } catch (err) {
        if (apiErrorCode(err) === "RECONCILIATION_SIGNOFF_NOT_FOUND") {
          return null;
        }
        throw err;
      }
    },
    enabled: Boolean(runId),
  });

  const findingsFilters = {
    limit: 25,
    severity: severityFilter || null,
    disposition: dispositionFilter || null,
  };
  const findingsQuery = useInfiniteQuery({
    queryKey: reconciliationKeys.findings(runId ?? "", findingsFilters),
    queryFn: ({ pageParam }) =>
      fetchReconciliationFindings(runId as string, { ...findingsFilters, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    enabled: Boolean(runId),
  });
  const findings = findingsQuery.data?.pages.flatMap((p) => p.items) ?? [];
  const findingsTotal = findingsQuery.data?.pages[0]?.total ?? null;

  const findingDetailQuery = useQuery({
    queryKey: reconciliationKeys.finding(selectedFindingId ?? ""),
    queryFn: () => fetchReconciliationFinding(selectedFindingId as string),
    enabled: Boolean(selectedFindingId),
  });

  const dispositionFinding = useQuery({
    queryKey: reconciliationKeys.finding(dispositionTarget ?? ""),
    queryFn: () => fetchReconciliationFinding(dispositionTarget as string),
    enabled: Boolean(dispositionTarget),
  });

  // Auto-clear a transient success/conflict banner rather than leaving it
  // on screen indefinitely.
  useEffect(() => {
    if (!banner) return;
    const t = setTimeout(() => setBanner(null), 6000);
    return () => clearTimeout(t);
  }, [banner]);

  function invalidateAfterDisposition(findingId: string) {
    queryClient.invalidateQueries({ queryKey: reconciliationKeys.finding(findingId) });
    if (runId) {
      queryClient.invalidateQueries({ queryKey: ["reconciliation", "run", runId, "findings"] });
      queryClient.invalidateQueries({ queryKey: reconciliationKeys.run(runId) });
    }
  }

  function invalidateAfterSignoff() {
    if (!runId) return;
    queryClient.invalidateQueries({ queryKey: reconciliationKeys.run(runId) });
    queryClient.invalidateQueries({ queryKey: reconciliationKeys.signoff(runId) });
    queryClient.invalidateQueries({ queryKey: reconciliationKeys.runs({ limit: 25 }) });
  }

  if (!runId) return null;

  if (runQuery.isLoading) {
    return <p className="text-sm text-[var(--text-muted)]">กำลังโหลดข้อมูลรอบการตรวจสอบ...</p>;
  }
  if (runQuery.isError || !runQuery.data) {
    return (
      <div className="flex flex-col items-start gap-2">
        <p className="text-sm text-status-repair">{apiErrorMessage(runQuery.error, "ไม่สามารถโหลดข้อมูลรอบการตรวจสอบได้")}</p>
        <button
          type="button"
          onClick={() => runQuery.refetch()}
          className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
        >
          ลองใหม่
        </button>
      </div>
    );
  }

  const run = runQuery.data;
  const signoff = signoffQuery.data ?? null;
  const canDispose = canSetReconciliationDisposition(user);
  const canSign = canSignOffReconciliation(user);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <Link to="/reconciliation" className="text-sm text-status-borrowed hover:underline">
          &larr; กลับไปยังรายการตรวจสอบข้อมูล
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-lg font-semibold">รอบการตรวจสอบข้อมูล</h1>
          <span
            className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${RECONCILIATION_RUN_STATUS_COLORS[run.status]}`}
          >
            {RECONCILIATION_RUN_STATUS_LABELS[run.status]}
          </span>
        </div>
      </div>

      {banner && (
        <div role="status" className="rounded-lg border border-[var(--border)] bg-[var(--border)]/10 p-3 text-sm">
          {banner}
        </div>
      )}

      {/* A. Run summary */}
      <section className="surface grid grid-cols-2 gap-3 rounded-xl border p-4 text-sm sm:grid-cols-4">
        <div>
          <div className="text-xs text-[var(--text-muted)]">เวอร์ชันกฎการตรวจสอบ</div>
          <div className="font-medium">{run.rule_version}</div>
        </div>
        <div>
          <div className="text-xs text-[var(--text-muted)]">วันที่สร้างรอบ</div>
          <div className="font-medium">{formatDateTimeInTimezone(run.created_at, "Asia/Bangkok")}</div>
        </div>
        <div>
          <div className="text-xs text-[var(--text-muted)]">รายการที่ตรวจพบทั้งหมด</div>
          <div className="font-medium">{run.summary_total_findings.toLocaleString()}</div>
        </div>
        <div>
          <div className="text-xs text-[var(--text-muted)]">ความรุนแรงสูง / ปานกลาง / ต่ำ</div>
          <div className="font-medium">
            {run.summary_high.toLocaleString()} / {run.summary_medium.toLocaleString()} / {run.summary_low.toLocaleString()}
          </div>
        </div>
      </section>

      {/* B. Approved coverage */}
      <section className="surface rounded-xl border p-4 text-sm">
        <h2 className="mb-2 text-sm font-semibold">ช่วงเวลาข้อมูลที่ได้รับอนุมัติ</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <div className="text-xs text-[var(--text-muted)]">ช่วงข้อมูลเดิม</div>
            <div className="font-medium">
              {formatDateTimeInTimezone(run.legacy_coverage_start, "Asia/Bangkok")} –{" "}
              {formatDateTimeInTimezone(run.legacy_coverage_end, "Asia/Bangkok")}
            </div>
          </div>
          <div>
            <div className="text-xs text-[var(--text-muted)]">เริ่มระบบใหม่</div>
            <div className="font-medium">{formatDateTimeInTimezone(run.live_system_start, "Asia/Bangkok")}</div>
          </div>
        </div>
      </section>

      {/* C. Review progress */}
      <section className="surface rounded-xl border p-4 text-sm">
        <h2 className="mb-2 text-sm font-semibold">ความคืบหน้าการตรวจสอบ</h2>
        <div className="flex flex-wrap gap-2">
          <span className="inline-flex items-center rounded-full border border-[var(--border)] px-2.5 py-1 text-xs font-medium">
            ทั้งหมด {run.summary_total_findings.toLocaleString()}
          </span>
          {Object.entries(run.finding_counts_by_disposition ?? {}).map(([key, count]) => (
            <span
              key={key}
              className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${
                key === "open"
                  ? "bg-status-out_of_service/15 text-status-out_of_service"
                  : RECONCILIATION_DISPOSITION_COLORS[key as ReconciliationDisposition] ?? ""
              }`}
            >
              {RECONCILIATION_DISPOSITION_FILTER_LABELS[key as "open" | ReconciliationDisposition] ?? key}: {count.toLocaleString()}
            </span>
          ))}
        </div>
      </section>

      {/* F. Sign-off area */}
      <section className="surface rounded-xl border p-4 text-sm">
        <h2 className="mb-2 text-sm font-semibold">การลงนามยืนยันผลการตรวจสอบ</h2>
        {signoffQuery.isLoading && <p className="text-[var(--text-muted)]">กำลังตรวจสอบสถานะการลงนาม...</p>}
        {signoffQuery.isError && (
          <p className="text-status-repair">{apiErrorMessage(signoffQuery.error, "ไม่สามารถตรวจสอบสถานะการลงนามได้")}</p>
        )}
        {!signoffQuery.isLoading && !signoffQuery.isError && signoff && (
          <div className="flex flex-col gap-2">
            <span className="inline-flex w-fit items-center rounded-full bg-status-available/15 px-2.5 py-1 text-xs font-medium text-status-available">
              ลงนามยืนยันแล้ว
            </span>
            <p className="text-[var(--text-muted)]">
              ยืนยันผลการตรวจสอบของรอบนี้เสร็จสมบูรณ์ ไม่ได้หมายความว่าข้อมูลเดิมทั้งหมดถูกต้องสมบูรณ์แบบ
            </p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <div>
                <div className="text-xs text-[var(--text-muted)]">ลงนามเมื่อ</div>
                <div className="font-medium">{formatDateTimeInTimezone(signoff.signed_off_at, "Asia/Bangkok")}</div>
              </div>
              <div>
                <div className="text-xs text-[var(--text-muted)]">เวอร์ชันกฎการตรวจสอบ ณ ตอนลงนาม</div>
                <div className="font-medium">
                  {typeof signoff.attestation_summary.rule_version === "string"
                    ? signoff.attestation_summary.rule_version
                    : run.rule_version}
                </div>
              </div>
            </div>
          </div>
        )}
        {!signoffQuery.isLoading && !signoffQuery.isError && !signoff && (
          <div className="flex flex-col items-start gap-3">
            <p className="text-[var(--text-muted)]">รอบการตรวจสอบนี้ยังไม่ได้ลงนามยืนยัน</p>
            {canSign && (
              <button
                type="button"
                ref={signOffTriggerRef}
                onClick={() => setSignOffDialogOpen(true)}
                disabled={run.status !== "completed"}
                className="rounded-lg bg-status-borrowed px-4 py-2.5 text-sm font-medium text-white disabled:opacity-50"
              >
                ลงนามยืนยันผลการตรวจสอบ
              </button>
            )}
          </div>
        )}
      </section>

      {/* D. Finding filters */}
      <section className="surface rounded-xl border p-4">
        <h2 className="mb-3 text-sm font-semibold">รายการที่ตรวจพบ</h2>
        <div className="flex flex-col gap-3 sm:flex-row">
          <div className="flex-1">
            <label htmlFor="reconciliation-disposition-filter" className="mb-1 block text-xs font-medium text-[var(--text-muted)]">
              สถานะการตรวจ
            </label>
            <select
              id="reconciliation-disposition-filter"
              value={dispositionFilter}
              onChange={(e) => setDispositionFilter(e.target.value as typeof dispositionFilter)}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm"
            >
              <option value="">ทั้งหมด</option>
              {DISPOSITION_FILTER_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>
                  {RECONCILIATION_DISPOSITION_FILTER_LABELS[opt]}
                </option>
              ))}
            </select>
          </div>
          <div className="flex-1">
            <label htmlFor="reconciliation-severity-filter" className="mb-1 block text-xs font-medium text-[var(--text-muted)]">
              ความรุนแรง
            </label>
            <select
              id="reconciliation-severity-filter"
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value as typeof severityFilter)}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm"
            >
              <option value="">ทั้งหมด</option>
              {SEVERITY_FILTER_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>
                  {RECONCILIATION_SEVERITY_LABELS[opt]}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* E. Finding list */}
        <div className="mt-4">
          {findingsQuery.isLoading && <p className="text-sm text-[var(--text-muted)]">กำลังโหลดรายการที่ตรวจพบ...</p>}
          {findingsQuery.isError && (
            <div className="flex flex-col items-start gap-2">
              <p className="text-sm text-status-repair">
                {apiErrorMessage(findingsQuery.error, "ไม่สามารถโหลดรายการที่ตรวจพบได้")}
              </p>
              <button
                type="button"
                onClick={() => findingsQuery.refetch()}
                className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
              >
                ลองใหม่
              </button>
            </div>
          )}
          {!findingsQuery.isLoading && !findingsQuery.isError && findings.length === 0 && (
            <p className="text-sm text-[var(--text-muted)]">ไม่พบรายการตามตัวกรองที่เลือก</p>
          )}
          {!findingsQuery.isLoading && !findingsQuery.isError && findings.length > 0 && (
            <ul className="flex flex-col gap-2">
              {findings.map((finding) => (
                <li key={finding.id}>
                  <button
                    type="button"
                    ref={findingTriggerRef}
                    onClick={() => setSelectedFindingId(finding.id)}
                    className="surface flex w-full flex-col gap-1.5 rounded-lg border p-3 text-left text-sm transition hover:border-status-borrowed"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-medium">{reconciliationFindingCodeLabel(finding.code)}</span>
                      <span
                        className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${RECONCILIATION_SEVERITY_COLORS[finding.severity]}`}
                      >
                        {RECONCILIATION_SEVERITY_LABELS[finding.severity]}
                      </span>
                    </div>
                    <div className="text-xs text-[var(--text-muted)]">
                      {finding.equipment_id ? `รหัสเครื่องมือ: ${finding.equipment_id}` : "ไม่ระบุเครื่องมือ"}
                    </div>
                    <div className="flex items-center justify-between gap-2">
                      <span
                        className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                          finding.disposition
                            ? RECONCILIATION_DISPOSITION_COLORS[finding.disposition]
                            : "bg-status-out_of_service/15 text-status-out_of_service"
                        }`}
                      >
                        {finding.disposition ? RECONCILIATION_DISPOSITION_LABELS[finding.disposition] : "ยังไม่ตรวจ"}
                      </span>
                      <span className="text-status-borrowed">ดูรายละเอียด</span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {!findingsQuery.isLoading && !findingsQuery.isError && findingsQuery.hasNextPage && (
            <button
              type="button"
              onClick={() => findingsQuery.fetchNextPage()}
              disabled={findingsQuery.isFetchingNextPage}
              className="mt-3 rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium disabled:opacity-50"
            >
              {findingsQuery.isFetchingNextPage ? "กำลังโหลด..." : "โหลดเพิ่มเติม"}
            </button>
          )}
          {!findingsQuery.isLoading && !findingsQuery.isError && !findingsQuery.hasNextPage && findingsTotal !== null && findings.length > 0 && (
            <p className="mt-2 text-xs text-[var(--text-muted)]">
              แสดง {findings.length.toLocaleString()} จาก {findingsTotal.toLocaleString()} รายการ
            </p>
          )}
        </div>
      </section>

      {selectedFindingId && (
        <div
          className="fixed inset-0 z-40 flex items-end justify-center bg-black/50 p-4 sm:items-center"
          onClick={() => setSelectedFindingId(null)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="reconciliation-finding-detail-title"
            onClick={(e) => e.stopPropagation()}
            className="surface flex max-h-[85vh] w-full max-w-lg flex-col gap-3 overflow-y-auto rounded-xl border p-4"
          >
            {findingDetailQuery.isLoading && <p className="text-sm text-[var(--text-muted)]">กำลังโหลดรายละเอียด...</p>}
            {findingDetailQuery.isError && (
              <p className="text-sm text-status-repair">{apiErrorMessage(findingDetailQuery.error, "ไม่สามารถโหลดรายละเอียดได้")}</p>
            )}
            {findingDetailQuery.data && (
              <FindingDetailContent
                finding={findingDetailQuery.data}
                canDispose={canDispose}
                onClose={() => setSelectedFindingId(null)}
                onDispose={() => {
                  setDispositionTarget(findingDetailQuery.data.id);
                }}
              />
            )}
          </div>
        </div>
      )}

      {dispositionTarget && dispositionFinding.data && (
        <ReconciliationDispositionDialog
          finding={dispositionFinding.data}
          onClose={() => setDispositionTarget(null)}
          onSettled={(message) => {
            setBanner(message);
            invalidateAfterDisposition(dispositionTarget);
            setDispositionTarget(null);
          }}
        />
      )}

      {signOffDialogOpen && (
        <ReconciliationSignOffDialog
          run={run}
          triggerRef={signOffTriggerRef}
          onClose={() => setSignOffDialogOpen(false)}
          onSettled={(message) => {
            setBanner(message);
            invalidateAfterSignoff();
            setSignOffDialogOpen(false);
          }}
        />
      )}
    </div>
  );
}

interface FindingDetailContentProps {
  finding: ReconciliationFindingDetail;
  canDispose: boolean;
  onClose: () => void;
  onDispose: () => void;
}

// Roadmap PR22F §17 of the task -- renders known evidence fields
// semantically where possible, with a collapsed raw-structured fallback
// rather than dumping JSON.stringify(...) as the primary UI. Never
// fabricates an interpretation not present in the backend's own evidence
// object.
function FindingDetailContent({ finding, canDispose, onClose, onDispose }: FindingDetailContentProps) {
  const evidenceEntries = Object.entries(finding.evidence ?? {});

  return (
    <>
      <div className="flex items-start justify-between gap-2">
        <h2 id="reconciliation-finding-detail-title" className="text-base font-semibold">
          {reconciliationFindingCodeLabel(finding.code)}
        </h2>
        <button type="button" onClick={onClose} aria-label="ปิด" className="rounded-lg px-2 py-1 text-lg">
          ×
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${RECONCILIATION_SEVERITY_COLORS[finding.severity]}`}>
          {RECONCILIATION_SEVERITY_LABELS[finding.severity]}
        </span>
        <span
          className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${
            finding.disposition
              ? RECONCILIATION_DISPOSITION_COLORS[finding.disposition]
              : "bg-status-out_of_service/15 text-status-out_of_service"
          }`}
        >
          {finding.disposition ? RECONCILIATION_DISPOSITION_LABELS[finding.disposition] : "ยังไม่ตรวจ"}
        </span>
      </div>

      {finding.equipment && (
        <div className="rounded-lg bg-[var(--border)]/20 p-3 text-sm">
          <div className="font-medium">{finding.equipment.equipment_name}</div>
          <div className="text-[var(--text-muted)]">
            {finding.equipment.asset_number}
            {finding.equipment.bcm_code ? ` · BCM ${finding.equipment.bcm_code}` : ""}
          </div>
        </div>
      )}

      {evidenceEntries.length > 0 && (
        <div className="text-sm">
          <div className="mb-1 font-medium">หลักฐานที่ตรวจพบ</div>
          <dl className="flex flex-col gap-1">
            {evidenceEntries.map(([key, value]) => (
              <div key={key} className="flex justify-between gap-2 border-b border-[var(--border)] py-1 text-xs last:border-0">
                <dt className="text-[var(--text-muted)]">{key}</dt>
                <dd className="text-right">{typeof value === "object" ? JSON.stringify(value) : String(value)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {finding.events.length > 0 && (
        <div className="text-sm">
          <div className="mb-1 font-medium">รายการเหตุการณ์ประวัติเดิมที่เกี่ยวข้อง</div>
          <ul className="flex flex-col gap-1">
            {finding.events.map((ev) => (
              <li key={ev.id} className="rounded-lg border border-[var(--border)] px-3 py-2 text-xs">
                {ev.event_type} · {formatDateTimeInTimezone(ev.occurred_at, "Asia/Bangkok")} · {ev.legacy_source_row_key}
              </li>
            ))}
          </ul>
        </div>
      )}

      {finding.disposition_note && (
        <div className="text-sm">
          <div className="mb-1 font-medium">หมายเหตุการตรวจสอบ</div>
          <p className="rounded-lg border border-[var(--border)] px-3 py-2 text-xs">{finding.disposition_note}</p>
        </div>
      )}

      {canDispose && (
        <button
          type="button"
          onClick={onDispose}
          className="mt-1 rounded-lg bg-status-borrowed px-4 py-2.5 text-sm font-medium text-white"
        >
          {finding.disposition ? "แก้ไขผลการตรวจสอบ" : "บันทึกผลการตรวจสอบ"}
        </button>
      )}
    </>
  );
}
