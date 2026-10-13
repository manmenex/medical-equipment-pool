import { api } from "@/services/api";
import { getImportSessionSummary } from "@/services/importSessionClient";
import type { Page } from "@/types";
import type {
  ImportSessionOut,
  ImportSessionSummaryOut,
  ImportSourceOut,
  LegacyHistoryDryRunPlanConfirmOut,
  LegacyHistoryDryRunPlanOut,
  LegacyHistoryDryRunPlanRowOut,
  ValidationFindingOut,
} from "@/types/legacyImportApi";

// Roadmap PR21E: the one seam every Legacy Transaction History real-workflow
// page/component goes through, mirroring services/equipmentMasterImportClient.ts's
// established shape. Every function here is a thin, honest wrapper over the
// actual merged backend routes (backend/app/api/v1/import_sessions.py for
// the generic session lifecycle, backend/app/api/v1/legacy_history_import.py
// for the PR21-specific dry-run plan review/confirm surface) -- no parsing,
// no row classification, no pairing, no Ward/BME resolution, no checksum
// computation. Every one of those decisions is made by the backend and only
// ever read back here.

export const LEGACY_TRANSACTION_HISTORY_DATASET_TYPE = "legacy_transaction_history";

export async function createLegacyHistorySession(): Promise<ImportSessionOut> {
  const resp = await api.post<ImportSessionOut>("/import-sessions", {
    dataset_type: LEGACY_TRANSACTION_HISTORY_DATASET_TYPE,
  });
  return resp.data;
}

export async function listLegacyHistorySessions(params: {
  limit?: number;
  cursor?: string | null;
}): Promise<Page<ImportSessionOut>> {
  const resp = await api.get<Page<ImportSessionOut>>("/import-sessions", {
    params: { dataset_type: LEGACY_TRANSACTION_HISTORY_DATASET_TYPE, ...params },
  });
  return resp.data;
}

export async function getLegacyHistorySession(sessionId: string): Promise<ImportSessionSummaryOut> {
  return getImportSessionSummary(sessionId);
}

// The single authoritative, server-checksummed registration path -- the
// frontend sends only the file and optional source_version; the server
// computes and returns the checksum from the bytes it actually received.
// That checksum (never one computed here) is what the caller passes on to
// the migration-authority lookup/approval flow
// (services/legacyMigrationAuthorityClient.ts).
export async function uploadLegacyHistorySource(
  sessionId: string,
  file: File,
  sourceVersion?: string
): Promise<ImportSourceOut> {
  const formData = new FormData();
  formData.append("file", file);
  if (sourceVersion) {
    formData.append("source_version", sourceVersion);
  }
  const resp = await api.post<ImportSourceOut>(`/import-sessions/${sessionId}/source/upload`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return resp.data;
}

export async function validateLegacyHistorySession(sessionId: string): Promise<ImportSessionOut> {
  const resp = await api.post<ImportSessionOut>(`/import-sessions/${sessionId}/validate`);
  return resp.data;
}

export async function dryRunLegacyHistorySession(sessionId: string): Promise<ImportSessionOut> {
  const resp = await api.post<ImportSessionOut>(`/import-sessions/${sessionId}/dry-run`);
  return resp.data;
}

// Bodyless -- the backend resolves the session's own exact confirmed plan
// internally and owns idempotency entirely via session state, exactly like
// Equipment Master's executeEquipmentMasterSession.
export async function executeLegacyHistorySession(sessionId: string): Promise<ImportSessionOut> {
  const resp = await api.post<ImportSessionOut>(`/import-sessions/${sessionId}/execute`);
  return resp.data;
}

export async function recoverLegacyHistorySession(sessionId: string): Promise<ImportSessionOut> {
  const resp = await api.post<ImportSessionOut>(`/import-sessions/${sessionId}/recover`);
  return resp.data;
}

export async function listLegacyHistoryValidationFindings(
  sessionId: string,
  params?: { limit?: number; cursor?: string | null; attempt_id?: string | null }
): Promise<Page<ValidationFindingOut>> {
  const resp = await api.get<Page<ValidationFindingOut>>(`/import-sessions/${sessionId}/errors`, { params });
  return resp.data;
}

// Roadmap PR21E0 §13: identity + summary only for the session's current
// `active` plan -- deliberately a SEPARATE route family from Equipment
// Master's `.../dry-run-plan` (which embeds a page of rows). Row content is
// fetched separately below, so pagination logic exists in exactly one
// place. Never accepts a plan id -- there is no "recompute" endpoint,
// mirroring PR20's own contract.
export async function getLegacyHistoryDryRunPlan(sessionId: string): Promise<LegacyHistoryDryRunPlanOut> {
  const resp = await api.get<LegacyHistoryDryRunPlanOut>(`/import-sessions/${sessionId}/legacy-history/dry-run-plan`);
  return resp.data;
}

// §14 of the task: `planId` must always be the exact plan identity already
// displayed to the operator via getLegacyHistoryDryRunPlan above -- the
// backend rejects a `plan_id` that does not belong to `sessionId`, and a
// `cursor` obtained while paging a different plan, both collapsed into
// IMPORT_DRY_RUN_PLAN_NOT_FOUND. This client never guesses or reuses a
// cursor across a different plan id.
export async function listLegacyHistoryDryRunPlanRows(
  sessionId: string,
  planId: string,
  params?: { limit?: number; cursor?: string | null }
): Promise<Page<LegacyHistoryDryRunPlanRowOut>> {
  const resp = await api.get<Page<LegacyHistoryDryRunPlanRowOut>>(
    `/import-sessions/${sessionId}/legacy-history/dry-run-plan/${planId}/rows`,
    { params }
  );
  return resp.data;
}

// The exact, persisted plan identity -- never "the latest plan" -- is
// always the plan_id already displayed to (and reviewed by) the operator
// via getLegacyHistoryDryRunPlan above; this function only ever forwards
// that exact id to the backend's own confirm endpoint.
export async function confirmLegacyHistoryDryRunPlan(
  sessionId: string,
  planId: string
): Promise<LegacyHistoryDryRunPlanConfirmOut> {
  const resp = await api.post<LegacyHistoryDryRunPlanConfirmOut>(
    `/import-sessions/${sessionId}/legacy-history/dry-run-plan/${planId}/confirm`
  );
  return resp.data;
}
