import type { PropsWithChildren } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "@/hooks/useAuth";
import { useAuthStore } from "@/store/authStore";

// The one page a user with a forced password change is allowed to reach.
// Exempting it is what stops the guard below from redirecting to itself
// forever.
export const CHANGE_PASSWORD_PATH = "/change-password";

export function ProtectedRoute({ children }: PropsWithChildren) {
  const accessToken = useAuthStore((s) => s.accessToken);
  const { user } = useAuth();
  const location = useLocation();

  if (!accessToken) {
    return <Navigate to="/login" replace />;
  }

  // `user` is null while the profile is still loading. Redirecting then
  // would send every authenticated user through the change-password screen
  // on every cold load, so the guard waits for a profile it has actually
  // seen. This is a usability guard, not a security boundary: the backend
  // is what decides whether a password is acceptable, and it re-checks the
  // current password on every change regardless of what this renders.
  if (user?.must_change_password && location.pathname !== CHANGE_PASSWORD_PATH) {
    return <Navigate to={CHANGE_PASSWORD_PATH} replace />;
  }

  return <>{children}</>;
}
