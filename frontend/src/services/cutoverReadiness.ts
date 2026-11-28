import { api } from "@/services/api";
import type { Page } from "@/types";
import type {
  CutoverDecisionCreateRequest,
  CutoverDecisionDetail,
  CutoverGateEvaluationResponse,
  CutoverReadinessRunDetail,
  CutoverReadinessRunListItem,
} from "@/types/cutoverReadiness";

// Roadmap PR23E -- Cutover Readiness Frontend / Operator Workflow. The one
// seam every cutover-readiness page/component goes through, mirroring
// services/reconciliation.ts's established shape exactly: thin, honest
// wrappers over the already-merged PR23B/C/D backend routes -- no
// filtering, no pagination, no eligibility, no gate/decision computation.
// Every one of those decisions is made by the backend and only ever read
// back here. The route family below (`/cutover-readiness-runs`) is the
// exact one backend/app/api/v1/cutover_readiness.py registers -- no
// alternate route is invented.

export interface CutoverReadinessRunListParams {
  limit?: number;
  cursor?: string | null;
}

export async function fetchCutoverReadinessRuns(
  params: CutoverReadinessRunListParams = {}
): Promise<Page<CutoverReadinessRunListItem>> {
  const resp = await api.get<Page<CutoverReadinessRunListItem>>("/cutover-readiness-runs", { params });
  return resp.data;
}

export async function fetchCutoverReadinessRun(runId: string): Promise<CutoverReadinessRunDetail> {
  const resp = await api.get<CutoverReadinessRunDetail>(`/cutover-readiness-runs/${runId}`);
  return resp.data;
}

// 422 (CUTOVER_READINESS_GATE_EVALUATION_REQUIRES_COMPLETED_RUN) is the
// normal "run not completed yet" state, not a page failure -- callers
// must branch on apiErrorCode(), never treat every non-2xx here as an
// error banner (§29 of the task).
export async function fetchCutoverGateEvaluation(runId: string): Promise<CutoverGateEvaluationResponse> {
  const resp = await api.get<CutoverGateEvaluationResponse>(`/cutover-readiness-runs/${runId}/gate-evaluation`);
  return resp.data;
}

// 404 (CUTOVER_DECISION_NOT_FOUND) is the normal "no decision recorded
// yet" state for a run, not a page failure -- distinct from
// CUTOVER_READINESS_RUN_NOT_FOUND (the run itself missing). Callers must
// branch on apiErrorCode(), never treat every non-2xx here as an error
// banner (§18/§25 of the task).
export async function fetchCutoverDecision(runId: string): Promise<CutoverDecisionDetail> {
  const resp = await api.get<CutoverDecisionDetail>(`/cutover-readiness-runs/${runId}/decision`);
  return resp.data;
}

// The frontend never computes Go/No-Go itself (§4 of the task) -- this
// call submits exactly the four DecisionCreateRequest fields and lets the
// POST response (success, or one of the structured CUTOVER_DECISION_*
// errors) be the only authority. The backend re-evaluates Gates A-F fresh
// inside the same transaction as the decision INSERT; nothing computed on
// the frontend before this call is trusted as the final answer.
export async function createCutoverDecision(
  runId: string,
  payload: CutoverDecisionCreateRequest
): Promise<CutoverDecisionDetail> {
  const resp = await api.post<CutoverDecisionDetail>(`/cutover-readiness-runs/${runId}/decision`, payload);
  return resp.data;
}

// Centralized query keys (mirrors reconciliationKeys's own established
// shape) -- every cutover-readiness page/component imports these rather
// than inlining its own string array, so cache invalidation after a
// decision can never miss a stale key spelled slightly differently
// elsewhere.
export const cutoverReadinessKeys = {
  all: ["cutoverReadiness"] as const,
  runs: (params: CutoverReadinessRunListParams = {}) => ["cutoverReadiness", "runs", params] as const,
  run: (runId: string) => ["cutoverReadiness", "run", runId] as const,
  gates: (runId: string) => ["cutoverReadiness", "run", runId, "gates"] as const,
  decision: (runId: string) => ["cutoverReadiness", "run", runId, "decision"] as const,
};
