import type { EquipmentSource } from "@/types";

// Roadmap PR33 (D14): "DEMO" / "ยืม" badge for demo/loan devices. Pool
// devices (or an unknown/absent source) render nothing.
export const SOURCE_BADGE_LABELS: Record<EquipmentSource, string | null> = {
  pool: null,
  demo: "DEMO",
  loan: "ยืม",
};

export const SOURCE_FILTER_LABELS: Record<EquipmentSource, string> = {
  pool: "Pool",
  demo: "Demo",
  loan: "ยืม",
};

export function sourceBadgeLabel(source: EquipmentSource | null | undefined): string | null {
  return source ? (SOURCE_BADGE_LABELS[source] ?? null) : null;
}

export function SourceBadge({ source }: { source: EquipmentSource | null | undefined }) {
  const label = sourceBadgeLabel(source);
  if (!label) return null;
  return (
    <span
      data-testid="source-badge"
      className="inline-flex items-center rounded bg-purple-500/15 px-1.5 py-0.5 text-[11px] font-semibold text-purple-400"
    >
      {label}
    </span>
  );
}
