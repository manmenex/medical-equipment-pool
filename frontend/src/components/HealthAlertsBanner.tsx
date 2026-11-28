import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { canViewHealthAlerts, useAuth } from "@/hooks/useAuth";
import { fetchHealthAlerts } from "@/services/system";

const POLL_MS = 5 * 60 * 1000;

const ALERT_LINKS: Record<string, string> = {
  sync_stale: "/sync-review",
  sync_review_queue: "/sync-review",
  hn_listener_disabled: "/admin",
};

// Administrators only; hidden when there is nothing to report (or the call fails).
export function HealthAlertsBanner() {
  const { user } = useAuth();
  const allowed = canViewHealthAlerts(user);
  const { data } = useQuery({
    queryKey: ["system", "health-alerts"],
    queryFn: fetchHealthAlerts,
    enabled: allowed,
    refetchInterval: POLL_MS,
  });

  if (!allowed || !data || data.length === 0) return null;
  return (
    <div role="alert" aria-label="สถานะระบบ" className="surface flex flex-col gap-1 rounded-lg border border-status-repair p-3 text-sm">
      {data.map((alert) => (
        <div key={alert.code} className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-status-repair">{alert.message_th}</span>
          {ALERT_LINKS[alert.code] && (
            <Link to={ALERT_LINKS[alert.code]} className="font-medium underline">
              ดูรายละเอียด
            </Link>
          )}
        </div>
      ))}
    </div>
  );
}
