import { api } from "@/services/api";
import type { ImportSessionSummaryOut } from "@/types/legacyImportApi";

// Roadmap PR21E: the one dataset-agnostic seam both
// services/equipmentMasterImportClient.ts and
// services/legacyHistoryImportClient.ts go through for `GET
// /import-sessions/{id}` -- this route never checks `dataset_type` at all
// (backend/app/api/v1/import_sessions.py), so there is exactly one real
// implementation to call, shared rather than duplicated per dataset.
// Callers that need to know *which* workflow a session belongs to read
// `dataset_type` off the returned summary themselves (see
// pages/LegacyImportSessionDetailPage.tsx) -- this function never infers
// or assumes a dataset type.
export async function getImportSessionSummary(sessionId: string): Promise<ImportSessionSummaryOut> {
  const resp = await api.get<ImportSessionSummaryOut>(`/import-sessions/${sessionId}`);
  return resp.data;
}
