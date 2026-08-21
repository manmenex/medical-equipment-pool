import { api } from "@/services/api";
import { getImportSessionSummary } from "@/services/importSessionClient";
import type { Page } from "@/types";
import type {
  DryRunPlanConfirmOut,
  DryRunPlanOut,
  ImportSessionOut,
  ImportSessionSummaryOut,
  ImportSourceOut,
  ValidationFindingOut,
} from "@/types/legacyImportApi";

// Roadmap PR20F/PR21E: the one seam every Equipment Master real-workflow
// page/component goes through. Every function here is a thin, honest
// wrapper over the actual merged backend routes
// (backend/app/api/v1/import_sessions.py) -- no business logic, no row
// classification, no client-side recomputation of anything the backend
// already decided. Never used for Legacy Transaction History, which goes
// through services/legacyHistoryImportClient.ts instead.

export const EQUIPMENT_MASTER_DATASET_TYPE = "equipment_master";

export async function createEquipmentMasterSession(): Promise<ImportSessionOut> {
  const resp = await api.post<ImportSessionOut>("/import-sessions", {
    dataset_type: EQUIPMENT_MASTER_DATASET_TYPE,
  });
  return resp.data;
}

export async function listEquipmentMasterSessions(params: {
  limit?: number;
  cursor?: string | null;
}): Promise<Page<ImportSessionOut>> {
  const resp = await api.get<Page<ImportSessionOut>>("/import-sessions", {
    params: { dataset_type: EQUIPMENT_MASTER_DATASET_TYPE, ...params },
  });
  return resp.data;
}

export async function getEquipmentMasterSession(sessionId: string): Promise<ImportSessionSummaryOut> {
  return getImportSessionSummary(sessionId);
}

// Roadmap PR20A (design §6.2): the single authoritative,
// server-checksummed registration path for this dataset_type -- the
// frontend sends only the file and optional source_version; the server
// computes the checksum from the bytes it actually receives. Never
// computed client-side as authority (a client-supplied checksum, if any,
// is advisory only per the backend's own contract, and this client never
// sends one).
export async function uploadEquipmentMasterSource(
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

export async function validateEquipmentMasterSession(sessionId: string): Promise<ImportSessionOut> {
  const resp = await api.post<ImportSessionOut>(`/import-sessions/${sessionId}/validate`);
  return resp.data;
}

export async function dryRunEquipmentMasterSession(sessionId: string): Promise<ImportSessionOut> {
  const resp = await api.post<ImportSessionOut>(`/import-sessions/${sessionId}/dry-run`);
  return resp.data;
}

// Bodyless -- exact PR19A/PR20E contract, preserved exactly. Never sends a
// plan id, expected_version, row set, or idempotency key: the backend
// resolves the session's own exact confirmed plan internally and owns
// idempotency entirely via session state (design §17: COMPLETED always
// replays the existing session; EXECUTING returns 409 in-progress).
export async function executeEquipmentMasterSession(sessionId: string): Promise<ImportSessionOut> {
  const resp = await api.post<ImportSessionOut>(`/import-sessions/${sessionId}/execute`);
  return resp.data;
}

export async function recoverEquipmentMasterSession(sessionId: string): Promise<ImportSessionOut> {
  const resp = await api.post<ImportSessionOut>(`/import-sessions/${sessionId}/recover`);
  return resp.data;
}

export async function getEquipmentMasterDryRunPlan(
  sessionId: string,
  params?: { limit?: number; cursor?: string | null }
): Promise<DryRunPlanOut> {
  const resp = await api.get<DryRunPlanOut>(`/import-sessions/${sessionId}/dry-run-plan`, { params });
  return resp.data;
}

// The exact, persisted plan identity -- never "the latest plan" -- is
// always the plan_id already displayed to (and reviewed by) the operator
// via getEquipmentMasterDryRunPlan above; this function only ever
// forwards that exact id to the backend's own confirm endpoint.
export async function confirmEquipmentMasterDryRunPlan(
  sessionId: string,
  planId: string
): Promise<DryRunPlanConfirmOut> {
  const resp = await api.post<DryRunPlanConfirmOut>(`/import-sessions/${sessionId}/dry-run-plan/${planId}/confirm`);
  return resp.data;
}

export async function listEquipmentMasterValidationFindings(
  sessionId: string,
  params?: { limit?: number; cursor?: string | null; attempt_id?: string | null }
): Promise<Page<ValidationFindingOut>> {
  const resp = await api.get<Page<ValidationFindingOut>>(`/import-sessions/${sessionId}/errors`, { params });
  return resp.data;
}
