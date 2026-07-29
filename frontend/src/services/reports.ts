import { api } from "@/services/api";
import type { Page, ReportOperatorOut, ReportTransactionOut, Shift } from "@/types";

// Roadmap PR17 Slice 3 (docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md §10.1/
// §10.2/§12): the approved filter set for both Receive and Issue reports --
// business_date_from/business_date_to/shift/ward_id/equipment_category_id/
// equipment_id/operator_id. `event` and `require_receipt` are never
// parameters here -- the backend pins both server-side (Roadmap PR17 Slice
// 1/2, backend/app/api/v1/reports.py) and this client must not attempt to
// override or duplicate that. dispatch_type/routine_round exist on the
// backend's Issue endpoint but are not part of this slice's approved
// filter set and are deliberately omitted here.
export interface ReportQueryParams {
  business_date_from?: string;
  business_date_to?: string;
  shift?: Shift;
  ward_id?: string;
  equipment_id?: string;
  equipment_category_id?: string;
  operator_id?: string;
  limit?: number;
  cursor?: string | null;
}

// GET /reports/receive (Roadmap PR17 §7.1/§8/§10.1): the backend
// unconditionally excludes OPEN transactions and pins event="receipt" --
// this client sends only the approved filters above and trusts the
// response exactly as returned.
export async function getReceiveReport(params: ReportQueryParams): Promise<Page<ReportTransactionOut>> {
  const resp = await api.get<Page<ReportTransactionOut>>("/reports/receive", { params });
  return resp.data;
}

// GET /reports/issue (Roadmap PR17 §7.2/§8/§10.2): both OPEN and CLOSED
// transactions are eligible on the backend -- this client never filters
// either out.
export async function getIssueReport(params: ReportQueryParams): Promise<Page<ReportTransactionOut>> {
  const resp = await api.get<Page<ReportTransactionOut>>("/reports/issue", { params });
  return resp.data;
}

export interface OperatorOptionsParams {
  q?: string;
  limit?: number;
  cursor?: string | null;
}

// GET /report-options/operators (Roadmap PR17 §10.4): the bounded,
// report-scoped operator lookup -- never GET /users. Must not be used for
// any user-management purpose.
export async function getOperatorOptions(params: OperatorOptionsParams = {}): Promise<Page<ReportOperatorOut>> {
  const resp = await api.get<Page<ReportOperatorOut>>("/report-options/operators", { params });
  return resp.data;
}
