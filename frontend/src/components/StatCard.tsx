import { Link } from "react-router-dom";

interface StatCardProps {
  label: string;
  value: number;
  to?: string;
  accentClassName?: string;
}

export function StatCard({ label, value, to, accentClassName = "text-status-available" }: StatCardProps) {
  const content = (
    <div className="surface flex flex-col gap-1 rounded-xl border p-4 transition hover:shadow-md">
      <span className="text-sm text-[var(--text-muted)]">{label}</span>
      <span className={`text-2xl font-semibold ${accentClassName}`}>{value.toLocaleString()}</span>
    </div>
  );
  return to ? <Link to={to}>{content}</Link> : content;
}
