// Roadmap PR12 (Inventory Import): thin wrappers over
// POST /import/preview and POST /import/commit. Both are multipart
// uploads of the same raw file -- commit never sends a previously
// fetched preview result back to the server; it re-uploads the file so
// the backend can independently re-parse and re-validate it (see
// backend/app/services/import_service.py's module docstring).
import { api } from "@/services/api";
import type { ImportCommitResponse, ImportPreviewResponse } from "@/types";

function buildImportFormData(file: File, updateExisting: boolean): FormData {
  const form = new FormData();
  form.append("file", file);
  form.append("update_existing", updateExisting ? "true" : "false");
  return form;
}

export async function previewImport(file: File, updateExisting: boolean): Promise<ImportPreviewResponse> {
  const resp = await api.post<ImportPreviewResponse>("/import/preview", buildImportFormData(file, updateExisting), {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return resp.data;
}

export async function commitImport(file: File, updateExisting: boolean): Promise<ImportCommitResponse> {
  const resp = await api.post<ImportCommitResponse>("/import/commit", buildImportFormData(file, updateExisting), {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return resp.data;
}
