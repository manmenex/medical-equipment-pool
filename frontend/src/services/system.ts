import { api } from "@/services/api";

export interface HealthAlert {
  code: string;
  severity: "warning" | "error" | string;
  message_th: string;
  since: string | null;
}

export async function fetchHealthAlerts(): Promise<HealthAlert[]> {
  const resp = await api.get<HealthAlert[]>("/system/health-alerts");
  return resp.data;
}
