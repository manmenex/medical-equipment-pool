import { api } from "@/services/api";
import type { PrintDocumentOut, ReportIdentity } from "@/types";

// Roadmap PR18C (docs/design/PR18_PRINTING_EXPORT_PLAN.md §6.2/§9): the
// single client for GET /reports/{report_id}/print-data
// (backend/app/api/v1/reports.py).
export type PrintReportFilters = Record<string, string | undefined>;

// Roadmap PR18C review 4837997016 (H2): an explicit, per-report-identity
// filter whitelist -- mirrors backend/app/api/v1/reports.py's own
// `_PRINT_DATA_APPLICABLE_FILTERS` exactly. The caller (ReportPrintPage)
// must never forward the raw `URLSearchParams`/`location.search` as-is:
// that would also drag along `cursor`, `limit`, or any future UI-only query
// param the on-screen report page might someday add, none of which this
// route accepts or should ever receive. The backend's own
// `_reject_inapplicable_print_data_filters` remains the authoritative,
// defense-in-depth check for a filter that is inapplicable to a given
// report_id -- this whitelist is the frontend's own explicit request
// construction, not a replacement for that backend check.
const PRINT_DATA_FILTER_KEYS: Record<ReportIdentity, readonly string[]> = {
  "receive-report": [
    "business_date_from",
    "business_date_to",
    "shift",
    "ward_id",
    "equipment_id",
    "equipment_category_id",
    "operator_id",
  ],
  "issue-report": [
    "business_date_from",
    "business_date_to",
    "shift",
    "ward_id",
    "equipment_id",
    "equipment_category_id",
    "operator_id",
    "dispatch_type",
    "routine_round",
  ],
  "equipment-verify-checklist": ["equipment_category_id", "status", "department_id"],
};

// Reads only the whitelisted keys for `reportId` out of `searchParams` --
// an unrecognized key (including `cursor`/`limit`, or a key belonging to a
// different report identity) is never included in the returned object, so
// it can never reach the print-data request.
export function buildPrintDataFilters(reportId: ReportIdentity, searchParams: URLSearchParams): PrintReportFilters {
  const filters: PrintReportFilters = {};
  for (const key of PRINT_DATA_FILTER_KEYS[reportId]) {
    const value = searchParams.get(key);
    if (value !== null) {
      filters[key] = value;
    }
  }
  return filters;
}

// Never sends `limit`/`cursor` -- the print-data route does not accept
// them and always returns the complete bounded result set matching the
// active filters (Owner Decision #1), not one cursor page.
export async function getReportPrintData(
  reportId: ReportIdentity,
  filters: PrintReportFilters
): Promise<PrintDocumentOut> {
  const resp = await api.get<PrintDocumentOut>(`/reports/${reportId}/print-data`, { params: filters });
  return resp.data;
}
