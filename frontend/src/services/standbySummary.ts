import { api } from "@/services/api";

// Roadmap PR34 (D16): standby summary. Pool staff + admin only (backend
// enforced). No patient data: only counts. Cut-offs: night = 08:00, day = 20:00
// (Asia/Bangkok) on the chosen date.
export type StandbyCutoff = "night" | "day";

export interface StandbyField {
  key: string;
  label: string;
  system_value: number | null;
  override_value: number | null;
  effective_value: number | null;
}

export interface StandbyBaseline {
  chargers: number | null;
  clamps: number | null;
  set_at: string | null;
}

export interface StandbySummary {
  date: string;
  cutoff: StandbyCutoff;
  cutoff_at: string;
  business_day_start: string;
  infusion: {
    categories: string[];
    wards: StandbyField[];
    bme_devices: StandbyField;
    chargers: StandbyField;
    clamps: StandbyField;
    ready: StandbyField;
    baseline: StandbyBaseline;
  };
  pneumatic: { categories: string[]; in_use: StandbyField; returned: StandbyField };
  approximations: string[];
}

export async function fetchStandbySummary(date: string, cutoff: StandbyCutoff): Promise<StandbySummary> {
  const resp = await api.get<StandbySummary>("/standby-summary", { params: { date, cutoff } });
  return resp.data;
}

export async function fetchStandbyText(date: string, cutoff: StandbyCutoff): Promise<string> {
  const resp = await api.get<string>("/standby-summary/text", {
    params: { date, cutoff },
    responseType: "text",
    transformResponse: (data) => data,
  });
  return resp.data;
}

/** `value: null` removes the edit so the system value applies again. */
export async function saveStandbyOverride(
  date: string,
  cutoff: StandbyCutoff,
  fieldKey: string,
  value: number | null,
): Promise<StandbySummary> {
  const resp = await api.put<StandbySummary>("/standby-summary/overrides", {
    date,
    cutoff,
    field_key: fieldKey,
    value,
  });
  return resp.data;
}

export async function saveStandbyBaseline(chargers: number, clamps: number): Promise<StandbyBaseline> {
  const resp = await api.put<StandbyBaseline>("/standby-summary/baseline", {
    category_role: "infusion",
    chargers,
    clamps,
  });
  return resp.data;
}
