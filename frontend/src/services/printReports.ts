import { api } from "@/services/api";
import type { PrintDocumentOut, ReportIdentity } from "@/types";

// Roadmap PR18C (docs/design/PR18_PRINTING_EXPORT_PLAN.md §6.2/§9): the
// single client for GET /reports/{report_id}/print-data
// (backend/app/api/v1/reports.py). Deliberately accepts the raw filter
// params the calling report page already has applied in its own URL (the
// same filter keys that report's own on-screen endpoint accepts) and
// forwards them verbatim -- this client does not decide which filters are
// applicable to a given report_id. The backend (app.api.v1.reports.
// _reject_inapplicable_print_data_filters) is the single source of truth
// for that and returns a structured 400 INVALID_INPUT for a filter that
// does not apply, which the caller surfaces as a visible error rather than
// silently dropping it or guessing.
//
// Never sends `limit`/`cursor` -- the print-data route does not accept
// them and always returns the complete bounded result set matching the
// active filters (Owner Decision #1), not one cursor page.
export type PrintReportFilters = Record<string, string | undefined>;

export async function getReportPrintData(
  reportId: ReportIdentity,
  filters: PrintReportFilters
): Promise<PrintDocumentOut> {
  const resp = await api.get<PrintDocumentOut>(`/reports/${reportId}/print-data`, { params: filters });
  return resp.data;
}
