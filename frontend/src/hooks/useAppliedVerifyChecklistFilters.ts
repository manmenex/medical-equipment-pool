import { useSearchParams } from "react-router-dom";

import type { VerifyChecklistQueryParams } from "@/services/reports";
import type { EquipmentStatus } from "@/types";

// Roadmap PR17 Slice 4: reads the same URL search params
// components/EquipmentVerifyChecklistFilterBar.tsx writes, shaped directly
// as the approved VerifyChecklistQueryParams -- the single place
// EquipmentVerifyChecklistPage derives its query key and request params
// from, mirroring useAppliedReportFilters.ts's own pattern for the
// Receive/Issue reports.
export function useAppliedVerifyChecklistFilters(): VerifyChecklistQueryParams {
  const [searchParams] = useSearchParams();
  return {
    equipment_category_id: searchParams.get("equipment_category_id") || undefined,
    status: (searchParams.get("status") as EquipmentStatus | null) || undefined,
    department_id: searchParams.get("department_id") || undefined,
  };
}
