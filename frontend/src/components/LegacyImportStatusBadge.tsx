import type { ImportSessionStatus } from "@/types/legacyImport";
import { IMPORT_STATUS_COLORS, IMPORT_STATUS_LABELS } from "@/utils/legacyImportLabels";

export function LegacyImportStatusBadge({ status }: { status: ImportSessionStatus }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${IMPORT_STATUS_COLORS[status]}`}>
      {IMPORT_STATUS_LABELS[status]}
    </span>
  );
}
