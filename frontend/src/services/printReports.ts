import { api } from "@/services/api";
import type { PrintDocumentOut, ReportIdentity } from "@/types";

// Roadmap PR18C (docs/design/PR18_PRINTING_EXPORT_PLAN.md §6.2/§9): the
// single client for GET /reports/{report_id}/print-data
// (backend/app/api/v1/reports.py).
export type PrintReportFilters = Record<string, string | undefined>;

// Roadmap PR18C review (second round, PR18C-H2R): the only parameters this
// route never accepts are the two pagination controls -- print-data always
// returns the complete bounded result set for the active filters (Owner
// Decision #1), never one cursor page. Every other query parameter must be
// preserved and sent through untouched: the backend's own
// `_reject_inapplicable_print_data_filters` (backend/app/api/v1/reports.py)
// is the single, authoritative place that decides whether a given filter
// applies to a given report identity, returning a structured
// `400 INVALID_INPUT` for one that doesn't. A frontend allowlist that
// silently dropped an inapplicable or unrecognized filter would hide that
// validation instead of surfacing it, and would also have to be kept in
// sync with the backend's own table by hand -- this function must never
// grow into that second, drifting copy (the first round's `PRINT_DATA_FILTER_KEYS`
// allowlist did exactly this, and was replaced by this narrower function).
const PRINT_DATA_PAGINATION_PARAM_KEYS = ["cursor", "limit"] as const;

// Clones `filters` and removes only `cursor`/`limit` -- every other key and
// value is preserved as given.
export function stripPrintDataPaginationParams(filters: PrintReportFilters): PrintReportFilters {
  const normalized = { ...filters };
  for (const key of PRINT_DATA_PAGINATION_PARAM_KEYS) {
    delete normalized[key];
  }
  return normalized;
}

// Reads every query param present on `searchParams` -- unlike an allowlist,
// this does not decide which keys are applicable to a given report
// identity; that decision belongs to the backend alone (see comment above).
export function buildPrintDataFilters(searchParams: URLSearchParams): PrintReportFilters {
  return Object.fromEntries(searchParams.entries());
}

export async function getReportPrintData(
  reportId: ReportIdentity,
  filters: PrintReportFilters
): Promise<PrintDocumentOut> {
  // Roadmap PR18C review (second round, PR18C-H2R): pagination stripping is
  // enforced here, inside the service itself -- not only by the caller's
  // own preprocessing. A caller that bypasses ReportPrintPage (or calls this
  // service directly with a raw `filters` object) must still be unable to
  // leak `cursor`/`limit` into a print-data request.
  const resp = await api.get<PrintDocumentOut>(`/reports/${reportId}/print-data`, {
    params: stripPrintDataPaginationParams(filters),
  });
  return resp.data;
}
