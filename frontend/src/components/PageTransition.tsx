import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";

/** Re-mounts on pathname change so the CSS enter animation replays. Never blocks interaction. */
export function PageTransition({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  return (
    <div key={pathname} className="page-enter" data-testid="page-transition" data-path={pathname}>
      {children}
    </div>
  );
}
