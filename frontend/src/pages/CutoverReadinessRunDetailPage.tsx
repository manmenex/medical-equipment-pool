import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { CutoverGoNoGoDialog } from "@/components/CutoverGoNoGoDialog";
import { canRecordCutoverDecision, canReviewCutoverReadiness, useAuth } from "@/hooks/useAuth";
import { apiErrorCode, apiErrorMessage } from "@/services/api";
import {
  cutoverReadinessKeys,
  fetchCutoverDecision,
  fetchCutoverGateEvaluation,
  fetchCutoverReadinessRun,
} from "@/services/cutoverReadiness";
import type { CutoverGateCode, CutoverGoNoGoDecisionValue } from "@/types/cutoverReadiness";
import {
  CUTOVER_DECISION_COLORS,
  CUTOVER_DECISION_LABELS,
  CUTOVER_GATE_CATEGORY_COLORS,
  CUTOVER_GATE_CATEGORY_LABELS,
  CUTOVER_GATE_LABELS,
  CUTOVER_GATE_STATUS_COLORS,
  CUTOVER_GATE_STATUS_LABELS,
  CUTOVER_RUN_STATUS_COLORS,
  CUTOVER_RUN_STATUS_LABELS,
} from "@/utils/cutoverReadinessLabels";
import { formatDateTimeInTimezone } from "@/utils/printFormat";

const GATE_ORDER: CutoverGateCode[] = ["A", "B", "C", "D", "E", "F"];

// Roadmap PR23E -- the primary cutover-readiness review screen (backend:
// PR23B's run read, PR23C's gate-evaluation, PR23D's decision
// read/write). Every mutation here (recording GO/NO-GO) only ever
// submits a request and reacts to the backend's response -- see
// CutoverGoNoGoDialog for the actual submit/error handling; this page
// owns query state and which dialog (if any) is open.
export function CutoverReadinessRunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const { user } = useAuth();
  const queryClient = useQueryClient();

  const [pendingDecision, setPendingDecision] = useState<CutoverGoNoGoDecisionValue | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const goTriggerRef = useRef<HTMLButtonElement | null>(null);
  const noGoTriggerRef = useRef<HTMLButtonElement | null>(null);

  const runQuery = useQuery({
    queryKey: cutoverReadinessKeys.run(runId ?? ""),
    queryFn: () => fetchCutoverReadinessRun(runId as string),
    enabled: Boolean(runId) && canReviewCutoverReadiness(user),
  });

  const run = runQuery.data;

  // §29 of the task -- gate evaluation requires a completed run
  // (CUTOVER_READINESS_GATE_EVALUATION_REQUIRES_COMPLETED_RUN); avoid
  // calling it at all for a clearly non-completed run rather than
  // treating a structured 422 precondition error as a page failure.
  const gateQuery = useQuery({
    queryKey: cutoverReadinessKeys.gates(runId ?? ""),
    queryFn: () => fetchCutoverGateEvaluation(runId as string),
    enabled: Boolean(runId) && run?.status === "completed",
  });

  // CUTOVER_DECISION_NOT_FOUND is the normal "no decision recorded yet"
  // state for a run, not a query failure (§18/§25 of the task) --
  // resolved to `null` here so the page can render the unsigned state
  // without a red error panel. Only this exact code is normalized --
  // CUTOVER_READINESS_RUN_NOT_FOUND (the run itself missing) is a
  // distinct, genuine error and must not be swallowed the same way
  // (§19 of the task: never normalize all 404s blindly).
  const decisionQuery = useQuery({
    queryKey: cutoverReadinessKeys.decision(runId ?? ""),
    queryFn: async () => {
      try {
        return await fetchCutoverDecision(runId as string);
      } catch (err) {
        if (apiErrorCode(err) === "CUTOVER_DECISION_NOT_FOUND") {
          return null;
        }
        throw err;
      }
    },
    enabled: Boolean(runId) && run?.status === "completed",
  });

  useEffect(() => {
    if (!banner) return;
    const t = setTimeout(() => setBanner(null), 6000);
    return () => clearTimeout(t);
  }, [banner]);

  function refetchAfterDecisionAttempt() {
    if (!runId) return;
    queryClient.invalidateQueries({ queryKey: cutoverReadinessKeys.run(runId) });
    queryClient.invalidateQueries({ queryKey: cutoverReadinessKeys.gates(runId) });
    queryClient.invalidateQueries({ queryKey: cutoverReadinessKeys.decision(runId) });
    queryClient.invalidateQueries({ queryKey: cutoverReadinessKeys.runs({ limit: 25 }) });
  }

  if (!runId) return null;

  if (runQuery.isLoading) {
    return <p className="text-sm text-[var(--text-muted)]">กำลังโหลดข้อมูลรอบความพร้อม...</p>;
  }
  if (runQuery.isError || !run) {
    return (
      <div className="flex flex-col items-start gap-2">
        <p className="text-sm text-status-repair">{apiErrorMessage(runQuery.error, "ไม่สามารถโหลดข้อมูลรอบความพร้อมได้")}</p>
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

  // §19 of the task -- fail-closed action visibility: only show the
  // decision action once every one of these has been positively
  // established, never on "unknown" (loading/error) state. This is a
  // usability gate only -- the backend independently enforces every one
  // of these preconditions again on submit (§20 of the task).
  const canShowDecisionAction =
    canRecordCutoverDecision(user) &&
    runQuery.isSuccess &&
    gateQuery.isSuccess &&
    decisionQuery.isSuccess &&
    decisionQuery.data === null;

  const hasBlocker = gateQuery.data?.has_blocker ?? false;
  const liveWarningItems = gateQuery.data?.items.filter((item) => item.category === "warning") ?? [];
  const existingDecision = decisionQuery.data ?? null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <Link to="/cutover-readiness" className="text-sm text-status-borrowed hover:underline">
          &larr; กลับไปยังรายการความพร้อมก่อนเปลี่ยนระบบ
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-lg font-semibold">รอบตรวจสอบความพร้อมก่อนเปลี่ยนระบบ</h1>
          <span
            className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${CUTOVER_RUN_STATUS_COLORS[run.status]}`}
          >
            {CUTOVER_RUN_STATUS_LABELS[run.status]}
          </span>
        </div>
      </div>

      {banner && (
        <div role="status" className="rounded-lg border border-[var(--border)] bg-[var(--border)]/10 p-3 text-sm">
          {banner}
        </div>
      )}

      {run.supersedes_run_id && (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--border)]/10 p-3 text-sm">
          รอบนี้ถูกสร้างขึ้นเพื่อแทนที่รอบความพร้อมก่อนหน้า
        </div>
      )}

      {/* A. Run summary */}
      <section className="surface grid grid-cols-2 gap-3 rounded-xl border p-4 text-sm sm:grid-cols-4">
        <div>
          <div className="text-xs text-[var(--text-muted)]">กำหนดเปลี่ยนระบบ</div>
          <div className="font-medium">{formatDateTimeInTimezone(run.cutover_instant, "Asia/Bangkok")}</div>
        </div>
        <div>
          <div className="text-xs text-[var(--text-muted)]">สร้างเมื่อ</div>
          <div className="font-medium">{formatDateTimeInTimezone(run.created_at, "Asia/Bangkok")}</div>
        </div>
        <div>
          <div className="text-xs text-[var(--text-muted)]">รหัสรุ่นระบบ (Application Baseline SHA)</div>
          <div className="break-all font-mono font-medium">{run.application_baseline_sha}</div>
        </div>
        <div>
          <div className="text-xs text-[var(--text-muted)]">วันที่บันทึกหลักฐานครบถ้วน</div>
          <div className="font-medium">
            {run.completed_at ? formatDateTimeInTimezone(run.completed_at, "Asia/Bangkok") : "ยังไม่บันทึกครบถ้วน"}
          </div>
        </div>
      </section>

      {/* B. Overall readiness summary */}
      {run.status === "completed" && (
        <section className="surface rounded-xl border p-4 text-sm">
          <h2 className="mb-2 text-sm font-semibold">สรุปผลการตรวจสอบความพร้อม</h2>
          {gateQuery.isLoading && <p className="text-[var(--text-muted)]">กำลังตรวจสอบความพร้อม...</p>}
          {gateQuery.isError && (
            <div className="flex flex-col items-start gap-2">
              <p className="text-status-repair">{apiErrorMessage(gateQuery.error, "ไม่สามารถตรวจสอบความพร้อมได้")}</p>
              <button
                type="button"
                onClick={() => gateQuery.refetch()}
                className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
              >
                ลองใหม่
              </button>
            </div>
          )}
          {gateQuery.isSuccess && gateQuery.data && (
            <p
              className={`rounded-lg p-3 font-medium ${
                hasBlocker
                  ? "bg-status-repair/15 text-status-repair"
                  : liveWarningItems.length > 0
                    ? "bg-status-pm/15 text-status-pm"
                    : "bg-status-available/15 text-status-available"
              }`}
            >
              {hasBlocker
                ? "ยังไม่พร้อมสำหรับการอนุมัติ GO"
                : liveWarningItems.length > 0
                  ? "ไม่มีรายการที่เป็นตัวบล็อก แต่ยังมีรายการที่ต้องรับทราบ"
                  : "ไม่พบตัวบล็อกหรือคำเตือนจากการตรวจอัตโนมัติ"}
            </p>
          )}
        </section>
      )}
      {run.status !== "completed" && (
        <section className="surface rounded-xl border p-4 text-sm text-[var(--text-muted)]">
          รอบนี้ยังไม่บันทึกหลักฐานครบถ้วน จึงยังไม่สามารถตรวจสอบ Gate A-F หรือบันทึกผล GO/NO-GO ได้
        </section>
      )}

      {/* C. Gate A-F presentation */}
      {run.status === "completed" && gateQuery.isSuccess && gateQuery.data && (
        <section className="flex flex-col gap-3">
          {GATE_ORDER.map((code) => {
            const summary = gateQuery.data.gates.find((g) => g.gate === code);
            const items = gateQuery.data.items.filter((item) => item.gate === code);
            if (!summary) return null;
            return (
              <div key={code} className="surface rounded-xl border p-4 text-sm">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <h3 className="font-semibold">
                    {code} — {CUTOVER_GATE_LABELS[code]}
                  </h3>
                  <span
                    className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${CUTOVER_GATE_STATUS_COLORS[summary.status]}`}
                  >
                    {CUTOVER_GATE_STATUS_LABELS[summary.status]}
                  </span>
                </div>
                <ul className="flex flex-col gap-2">
                  {items.map((item, idx) => (
                    <li
                      key={`${item.code}-${idx}`}
                      className="rounded-lg border border-[var(--border)] p-2.5"
                    >
                      <div className="mb-1 flex flex-wrap items-center gap-2">
                        <span
                          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${CUTOVER_GATE_CATEGORY_COLORS[item.category]}`}
                        >
                          {CUTOVER_GATE_CATEGORY_LABELS[item.category]}
                        </span>
                      </div>
                      <p>{item.message}</p>
                      {item.manual_attestation_required && (
                        <p className="mt-1 text-xs text-[var(--text-muted)]">
                          รายการนี้ระบบไม่สามารถตรวจสอบอัตโนมัติได้ ต้องตรวจสอบโดยผู้รับผิดชอบ
                        </p>
                      )}
                    </li>
                  ))}
                  {items.length === 0 && <li className="text-[var(--text-muted)]">ไม่มีรายการ</li>}
                </ul>
                {code === "E" && (
                  <Link to="/borrow" className="mt-2 inline-block text-sm text-status-borrowed hover:underline">
                    ไปหน้าส่งเครื่อง
                  </Link>
                )}
              </div>
            );
          })}
        </section>
      )}

      {/* D. Decision section */}
      {run.status === "completed" && (
        <section className="surface rounded-xl border p-4 text-sm">
          <h2 className="mb-2 text-sm font-semibold">ผลการอนุมัติ GO / NO-GO</h2>
          {decisionQuery.isLoading && <p className="text-[var(--text-muted)]">กำลังตรวจสอบผลการอนุมัติ...</p>}
          {decisionQuery.isError && (
            <p className="text-status-repair">{apiErrorMessage(decisionQuery.error, "ไม่สามารถตรวจสอบผลการอนุมัติได้")}</p>
          )}
          {decisionQuery.isSuccess && existingDecision && (
            <div className="flex flex-col gap-2">
              <span
                className={`inline-flex w-fit items-center rounded-full px-2.5 py-1 text-xs font-medium ${CUTOVER_DECISION_COLORS[existingDecision.decision]}`}
              >
                {CUTOVER_DECISION_LABELS[existingDecision.decision]}
              </span>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <div>
                  <div className="text-xs text-[var(--text-muted)]">บันทึกเมื่อ</div>
                  <div className="font-medium">{formatDateTimeInTimezone(existingDecision.recorded_at, "Asia/Bangkok")}</div>
                </div>
                <div>
                  <div className="text-xs text-[var(--text-muted)]">เวอร์ชันรอบ ณ ตอนบันทึก</div>
                  <div className="font-medium">{existingDecision.run_version_at_decision}</div>
                </div>
              </div>
              {existingDecision.acknowledged_warning_codes.length > 0 && (
                <div>
                  <div className="mb-1 text-xs text-[var(--text-muted)]">คำเตือนที่รับทราบแล้ว ณ ตอนบันทึก</div>
                  <ul className="flex flex-wrap gap-1.5">
                    {existingDecision.acknowledged_warning_codes.map((code) => (
                      <li key={code} className="rounded-full border border-[var(--border)] px-2 py-0.5 text-xs">
                        {code}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {existingDecision.no_go_reason && (
                <div>
                  <div className="mb-1 text-xs text-[var(--text-muted)]">เหตุผล</div>
                  <p className="rounded-lg border border-[var(--border)] px-3 py-2 text-xs">{existingDecision.no_go_reason}</p>
                </div>
              )}
              <p className="text-xs text-[var(--text-muted)]">ผลการอนุมัตินี้เป็นข้อมูลถาวร ไม่สามารถแก้ไขหรือบันทึกซ้ำได้</p>
            </div>
          )}
          {decisionQuery.isSuccess && !existingDecision && (
            <div className="flex flex-col items-start gap-3">
              <p className="text-[var(--text-muted)]">รอบนี้ยังไม่มีการบันทึกผล GO/NO-GO</p>
              {canShowDecisionAction && (
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    ref={goTriggerRef}
                    onClick={() => setPendingDecision("GO")}
                    disabled={hasBlocker}
                    title={hasBlocker ? "ไม่สามารถอนุมัติ GO ได้ขณะมีตัวบล็อก" : undefined}
                    className="rounded-lg bg-status-available px-4 py-2.5 text-sm font-medium text-white disabled:opacity-50"
                  >
                    อนุมัติ GO
                  </button>
                  <button
                    type="button"
                    ref={noGoTriggerRef}
                    onClick={() => setPendingDecision("NO_GO")}
                    className="rounded-lg bg-status-repair px-4 py-2.5 text-sm font-medium text-white"
                  >
                    ไม่อนุมัติ NO-GO
                  </button>
                </div>
              )}
            </div>
          )}
        </section>
      )}

      {/* Evidence details (secondary/expandable) */}
      <details className="surface rounded-xl border p-4 text-sm">
        <summary className="cursor-pointer text-sm font-semibold">รายละเอียดหลักฐานเชิงเทคนิค</summary>
        <dl className="mt-3 flex flex-col gap-1.5">
          {[
            ["รหัสรุ่นฐานข้อมูล (Database Migration Head)", run.database_migration_head],
            ["รหัสแหล่งข้อมูลทะเบียนเครื่องมือ", run.equipment_master_import_source_id],
            ["รหัสสิทธิ์อนุมัติข้อมูลเดิม", run.legacy_migration_authority_id],
            ["รหัสขอบเขตข้อมูลเดิม", run.legacy_coverage_id],
            ["รหัสรอบตรวจสอบข้อมูล", run.reconciliation_run_id],
            ["รหัสการลงนามยืนยัน", run.reconciliation_signoff_id],
            ["ตรวจสอบสถานะปัจจุบันเมื่อ", run.current_state_verified_at],
            ["ผู้ตรวจสอบสถานะปัจจุบัน", run.current_state_verified_by_user_id],
            ["จำนวนขอบเขตที่ตรวจสอบ", run.current_state_verification_scope_count],
            ["อ้างอิงการตรวจสอบสถานะปัจจุบัน", run.current_state_verification_reference],
            ["รหัสหอผู้ป่วยนำร่อง", run.pilot_ward_id],
            ["ผู้อนุมัติด้านปฏิบัติการ", run.operational_approver_reference],
          ].map(([label, value]) => (
            <div key={label as string} className="flex justify-between gap-2 border-b border-[var(--border)] py-1 text-xs last:border-0">
              <dt className="text-[var(--text-muted)]">{label}</dt>
              <dd className="break-all text-right font-mono">{value != null && value !== "" ? String(value) : "—"}</dd>
            </div>
          ))}
        </dl>
      </details>

      {pendingDecision && (
        <CutoverGoNoGoDialog
          run={run}
          decision={pendingDecision}
          liveWarningItems={liveWarningItems}
          triggerRef={pendingDecision === "GO" ? goTriggerRef : noGoTriggerRef}
          onClose={() => setPendingDecision(null)}
          onResolved={(message) => {
            setBanner(message);
            refetchAfterDecisionAttempt();
            setPendingDecision(null);
          }}
          onStaleDataDetected={() => refetchAfterDecisionAttempt()}
        />
      )}
    </div>
  );
}
