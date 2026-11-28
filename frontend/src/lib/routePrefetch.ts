// Warm a route's lazy chunk on nav hover/focus/touchstart. The import()
// specifiers match App.tsx's lazy() calls, so the chunk is shared.
const loaders: Record<string, () => Promise<unknown>> = {
  "/": () => import("@/pages/DashboardPage"),
  "/equipment": () => import("@/pages/EquipmentListPage"),
  "/reports": () => import("@/pages/ReportsPage"),
  "/borrow": () => import("@/pages/BorrowPage"),
  "/return": () => import("@/pages/ReturnPage"),
  "/monitor": () => import("@/pages/MonitorPage"),
  "/standby-summary": () => import("@/pages/StandbySummaryPage"),
  "/settings": () => import("@/pages/SettingsPage"),
};

const started = new Set<string>();

export function prefetchRoute(path: string): void {
  const load = loaders[path];
  if (!load || started.has(path)) return;
  started.add(path);
  load().catch(() => started.delete(path));
}

export function prefetchProps(path: string) {
  const go = () => prefetchRoute(path);
  return { onMouseEnter: go, onFocus: go, onTouchStart: go };
}
