import type { CSSProperties, ReactNode } from "react";

interface SkeletonProps {
  className?: string;
  style?: CSSProperties;
}

/** One gray block (theme tokens only; shimmer is CSS, off under reduced motion). */
export function Skeleton({ className = "", style }: SkeletonProps) {
  return <div aria-hidden="true" className={`skeleton ${className}`} style={style} />;
}

interface SkeletonGroupProps {
  /** Accessible loading text, kept screen-reader-only. */
  label?: string;
  className?: string;
  children: ReactNode;
}

/** Wrapper that announces loading (aria-busy + sr-only text) around skeleton blocks. */
export function SkeletonGroup({ label = "กำลังโหลด...", className = "", children }: SkeletonGroupProps) {
  return (
    <div role="status" aria-busy="true" data-testid="skeleton-group" className={className}>
      <span className="sr-only">{label}</span>
      {children}
    </div>
  );
}

/** Grid of stat-card-sized blocks (Dashboard). */
export function StatCardsSkeleton({ count = 8, label }: { count?: number; label?: string }) {
  return (
    <SkeletonGroup label={label} className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-8">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="surface flex flex-col gap-2 rounded-xl border p-4">
          <Skeleton className="h-5 w-3/4" />
          <Skeleton className="h-8 w-1/2" />
        </div>
      ))}
    </SkeletonGroup>
  );
}

/** Stacked row blocks for lists and report tables. */
export function ListSkeleton({
  rows = 6,
  label,
  rowClassName = "h-14",
}: {
  rows?: number;
  label?: string;
  rowClassName?: string;
}) {
  return (
    <SkeletonGroup label={label} className="flex flex-col gap-2">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={`${rowClassName} w-full`} />
      ))}
    </SkeletonGroup>
  );
}

/** Generic page-level fallback (heading + blocks); usable as a Suspense fallback. */
export function PageSkeleton({ label }: { label?: string }) {
  return (
    <SkeletonGroup label={label} className="flex flex-col gap-4">
      <Skeleton className="h-8 w-1/3" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-24 w-full" />
    </SkeletonGroup>
  );
}
