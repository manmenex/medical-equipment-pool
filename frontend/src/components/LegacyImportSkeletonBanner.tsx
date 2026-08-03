// PR19B (Legacy Import Frontend Skeleton): every PR19B page renders this so
// a reviewer can never mistake mock/demo content for a working importer.
// Task brief, "Mock boundary": "This indicator must be visible to users
// reviewing the skeleton."
export function LegacyImportSkeletonBanner() {
  return (
    <div
      role="status"
      className="rounded-lg border border-dashed border-status-pm bg-status-pm/10 px-3 py-2 text-sm font-medium text-status-pm"
    >
      ต้นแบบหน้าจอ — ยังไม่มีการนำเข้าข้อมูลจริง
    </div>
  );
}
