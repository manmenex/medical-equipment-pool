import { useSearchParams } from "react-router-dom";

import type { ReportQueryParams } from "@/services/reports";
import type { Shift } from "@/types";

// Roadmap PR17 Slice 3: reads the same URL search params
// components/ReportFilterBar.tsx writes, shaped directly as the approved
// ReportQueryParams -- the single place ReceiveReportPage/IssueReportPage
// derive their query key and request params from, so both pages read the
// applied filters identically.
export function useAppliedReportFilters(): ReportQueryParams {
  const [searchParams] = useSearchParams();
  return {
    business_date_from: searchParams.get("business_date_from") || undefined,
    business_date_to: searchParams.get("business_date_to") || undefined,
    shift: (searchParams.get("shift") as Shift | null) || undefined,
    ward_id: searchParams.get("ward_id") || undefined,
    equipment_category_id: searchParams.get("equipment_category_id") || undefined,
    equipment_id: searchParams.get("equipment_id") || undefined,
    operator_id: searchParams.get("operator_id") || undefined,
  };
}
