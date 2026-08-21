import { Suspense, lazy } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { ProtectedRoute } from "@/components/ProtectedRoute";
import { AppShell } from "@/layouts/AppShell";
import { LoginPage } from "@/pages/LoginPage";

const DashboardPage = lazy(() => import("@/pages/DashboardPage").then((m) => ({ default: m.DashboardPage })));
const EquipmentListPage = lazy(() =>
  import("@/pages/EquipmentListPage").then((m) => ({ default: m.EquipmentListPage }))
);
const EquipmentDetailPage = lazy(() =>
  import("@/pages/EquipmentDetailPage").then((m) => ({ default: m.EquipmentDetailPage }))
);
const BorrowPage = lazy(() => import("@/pages/BorrowPage").then((m) => ({ default: m.BorrowPage })));
const ReturnPage = lazy(() => import("@/pages/ReturnPage").then((m) => ({ default: m.ReturnPage })));
const ScanPage = lazy(() => import("@/pages/ScanPage").then((m) => ({ default: m.ScanPage })));
const ReportsPage = lazy(() => import("@/pages/ReportsPage").then((m) => ({ default: m.ReportsPage })));
const ReceiveReportPage = lazy(() =>
  import("@/pages/ReceiveReportPage").then((m) => ({ default: m.ReceiveReportPage }))
);
const IssueReportPage = lazy(() =>
  import("@/pages/IssueReportPage").then((m) => ({ default: m.IssueReportPage }))
);
const EquipmentVerifyChecklistPage = lazy(() =>
  import("@/pages/EquipmentVerifyChecklistPage").then((m) => ({ default: m.EquipmentVerifyChecklistPage }))
);
const ReportPrintPage = lazy(() => import("@/pages/ReportPrintPage").then((m) => ({ default: m.ReportPrintPage })));
const AdminPage = lazy(() => import("@/pages/AdminPage").then((m) => ({ default: m.AdminPage })));
const LegacyImportListPage = lazy(() =>
  import("@/pages/LegacyImportListPage").then((m) => ({ default: m.LegacyImportListPage }))
);
const LegacyImportCreatePage = lazy(() =>
  import("@/pages/LegacyImportCreatePage").then((m) => ({ default: m.LegacyImportCreatePage }))
);
const LegacyImportSessionDetailPage = lazy(() =>
  import("@/pages/LegacyImportSessionDetailPage").then((m) => ({ default: m.LegacyImportSessionDetailPage }))
);
const SettingsPage = lazy(() => import("@/pages/SettingsPage").then((m) => ({ default: m.SettingsPage })));
const NotFoundPage = lazy(() => import("@/pages/NotFoundPage").then((m) => ({ default: m.NotFoundPage })));

function PageFallback() {
  return <p className="p-4 text-sm text-[var(--text-muted)]">กำลังโหลด...</p>;
}

export function App() {
  return (
    <Suspense fallback={<PageFallback />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        {/* Roadmap PR18C (docs/design/PR18_PRINTING_EXPORT_PLAN.md §9/§22):
            a bare print view, deliberately outside the AppShell-wrapping
            route below so no navigation/dashboard chrome renders in the
            printed output -- guarded by the same ProtectedRoute as every
            authenticated page, just not the shell. Mirrors /login's own
            "outside AppShell" route shape. */}
        <Route
          path="/reports/:reportId/print"
          element={
            <ProtectedRoute>
              <ReportPrintPage />
            </ProtectedRoute>
          }
        />
        <Route
          element={
            <ProtectedRoute>
              <AppShell />
            </ProtectedRoute>
          }
        >
          <Route path="/" element={<DashboardPage />} />
          <Route path="/equipment" element={<EquipmentListPage />} />
          <Route path="/equipment/:id" element={<EquipmentDetailPage />} />
          <Route path="/scan" element={<ScanPage />} />
          <Route path="/borrow" element={<BorrowPage />} />
          <Route path="/return" element={<ReturnPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          {/* Roadmap PR17 Slice 3: new sub-routes under the existing
              /reports route (docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md
              §12) -- additional, separate report screens, not a
              replacement for /reports. */}
          <Route path="/reports/receive" element={<ReceiveReportPage />} />
          <Route path="/reports/issue" element={<IssueReportPage />} />
          {/* Roadmap PR17 Slice 4: the final PR17 report screen, same
              /reports sub-route convention as Slice 3's two screens. */}
          <Route path="/reports/equipment-verify-checklist" element={<EquipmentVerifyChecklistPage />} />
          {/* Roadmap PR20F/PR21E: real, backend-integrated import routes for
              both Equipment Master and Legacy Transaction History -- see
              pages/LegacyImport*.tsx. Which workflow panel renders on the
              detail route is decided by the session's own real
              dataset_type, never by the route/id shape. */}
          <Route path="/imports" element={<LegacyImportListPage />} />
          <Route path="/imports/new" element={<LegacyImportCreatePage />} />
          <Route path="/imports/:sessionId" element={<LegacyImportSessionDetailPage />} />
          <Route path="/admin" element={<AdminPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
        <Route path="/404" element={<NotFoundPage />} />
        <Route path="*" element={<Navigate to="/404" replace />} />
      </Routes>
    </Suspense>
  );
}
