import { api } from "@/services/api";
import type { Page } from "@/types";
import type {
  ReconciliationFindingDetail,
  ReconciliationFindingDispositionRequest,
  ReconciliationFindingListItem,
  ReconciliationRunDetail,
  ReconciliationRunListItem,
  ReconciliationSignOffDetail,
  ReconciliationSignOffRequest,
} from "@/types/reconciliation";

// Roadmap PR22F -- Reconciliation Frontend Integration. The one seam
// every reconciliation page/component goes through, mirroring
// services/legacyHistoryImportClient.ts's established shape exactly:
// thin, honest wrappers over the already-merged PR22D/PR22E backend
// routes -- no filtering, no pagination, no eligibility, no attestation
// construction. Every one of those decisions is made by the backend and
// only ever read back here.

export interface ReconciliationRunListParams {
  limit?: number;
  cursor?: string | null;
}

export async function fetchReconciliationRuns(
  params: ReconciliationRunListParams = {}
): Promise<Page<ReconciliationRunListItem>> {
  const resp = await api.get<Page<ReconciliationRunListItem>>("/legacy-reconciliation-runs", { params });
  return resp.data;
}

export async function fetchReconciliationRun(runId: string): Promise<ReconciliationRunDetail> {
  const resp = await api.get<ReconciliationRunDetail>(`/legacy-reconciliation-runs/${runId}`);
  return resp.data;
}

export interface ReconciliationFindingListParams {
  limit?: number;
  cursor?: string | null;
  code?: string | null;
  severity?: string | null;
  // Passed straight through to the backend's own filter convention --
  // "open" (or "null") selects undispositioned findings, one of the four
  // closed disposition values selects that exact disposition, and
  // omitted/undefined means no disposition filter at all. The frontend
  // never re-implements this matching client-side.
  disposition?: string | null;
  equipment_id?: string | null;
}

export async function fetchReconciliationFindings(
  runId: string,
  params: ReconciliationFindingListParams = {}
): Promise<Page<ReconciliationFindingListItem>> {
  const resp = await api.get<Page<ReconciliationFindingListItem>>(`/legacy-reconciliation-runs/${runId}/findings`, {
    params,
  });
  return resp.data;
}

export async function fetchReconciliationFinding(findingId: string): Promise<ReconciliationFindingDetail> {
  const resp = await api.get<ReconciliationFindingDetail>(`/legacy-reconciliation-findings/${findingId}`);
  return resp.data;
}

// The caller must always pass the `expected_version` last read from the
// server (the currently loaded finding's own `version`) -- never a
// guessed or client-incremented value (see docs/api/ERROR_CODES.md's
// RECONCILIATION_FINDING_VERSION_CONFLICT). A 409 here is expected,
// routine backend behavior, not a bug -- callers must handle it via
// apiErrorCode(), never auto-retry with the same stale value.
export async function updateReconciliationFindingDisposition(
  findingId: string,
  payload: ReconciliationFindingDispositionRequest
): Promise<ReconciliationFindingDetail> {
  const resp = await api.patch<ReconciliationFindingDetail>(
    `/legacy-reconciliation-findings/${findingId}/disposition`,
    payload
  );
  return resp.data;
}

// 404 (RECONCILIATION_SIGNOFF_NOT_FOUND) is the normal "not yet signed
// off" state for a run, not a page failure -- callers must branch on
// apiErrorCode(), never treat every non-2xx here as an error banner.
export async function fetchReconciliationSignoff(runId: string): Promise<ReconciliationSignOffDetail> {
  const resp = await api.get<ReconciliationSignOffDetail>(`/legacy-reconciliation-runs/${runId}/sign-off`);
  return resp.data;
}

// Deliberately accepts only `expected_version` -- the backend builds the
// entire attestation from database truth (PR22E §8/§20-21 of the task).
// Never construct or send attestation_summary/rule_version/coverage
// timestamps/finding counts/signer id from the frontend.
export async function createReconciliationSignoff(
  runId: string,
  payload: ReconciliationSignOffRequest
): Promise<ReconciliationSignOffDetail> {
  const resp = await api.post<ReconciliationSignOffDetail>(`/legacy-reconciliation-runs/${runId}/sign-off`, payload);
  return resp.data;
}

// Centralized query keys (§31 of the task) -- every reconciliation
// page/component imports these rather than inlining its own string
// array, so cache invalidation after a mutation can never miss a stale
// key spelled slightly differently elsewhere.
export const reconciliationKeys = {
  all: ["reconciliation"] as const,
  runs: (params: ReconciliationRunListParams = {}) => ["reconciliation", "runs", params] as const,
  run: (runId: string) => ["reconciliation", "run", runId] as const,
  findings: (runId: string, filters: ReconciliationFindingListParams = {}) =>
    ["reconciliation", "run", runId, "findings", filters] as const,
  finding: (findingId: string) => ["reconciliation", "finding", findingId] as const,
  signoff: (runId: string) => ["reconciliation", "run", runId, "signoff"] as const,
};
