// Roadmap PR12 (Inventory Import): thin wrappers over
// POST /import/preview and POST /import/commit. Both are multipart
// uploads of the same raw file -- commit never sends a previously
// fetched preview result back to the server; it re-uploads the file so
// the backend can independently re-parse and re-validate it (see
// backend/app/services/import_service.py's module docstring).
//
// Review finding PR12-H1R / Repository Owner decision: Roadmap PR12 is
// update-only. There is no frontend path that can request anything else
// -- `update_existing` is always sent as "true"; the backend rejects
// `false` outright (kept in the request shape only for API
// compatibility, see app.services.import_service.process_import).
import { api } from "@/services/api";
import type { ImportCommitResponse, ImportPreviewResponse } from "@/types";

function buildImportFormData(file: File): FormData {
  const form = new FormData();
  form.append("file", file);
  form.append("update_existing", "true");
  return form;
}

export async function previewImport(file: File): Promise<ImportPreviewResponse> {
  const resp = await api.post<ImportPreviewResponse>("/import/preview", buildImportFormData(file), {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return resp.data;
}

export async function commitImport(file: File): Promise<ImportCommitResponse> {
  const resp = await api.post<ImportCommitResponse>("/import/commit", buildImportFormData(file), {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return resp.data;
}
