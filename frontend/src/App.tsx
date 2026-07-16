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
const ReportsPage = lazy(() => import("@/pages/ReportsPage").then((m) => ({ default: m.ReportsPage })));
const AdminPage = lazy(() => import("@/pages/AdminPage").then((m) => ({ default: m.AdminPage })));
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
          <Route path="/borrow" element={<BorrowPage />} />
          <Route path="/return" element={<ReturnPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/admin" element={<AdminPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
        <Route path="/404" element={<NotFoundPage />} />
        <Route path="*" element={<Navigate to="/404" replace />} />
      </Routes>
    </Suspense>
  );
}
