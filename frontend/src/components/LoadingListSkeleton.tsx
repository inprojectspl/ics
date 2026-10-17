import { DATA_ROW } from "./ui/DataList";

/** Loading state of a `DataList` with one- or two-line rows. */
export function LoadingListSkeleton({ rows = 5, leading = true }: { rows?: number; leading?: boolean }) {
  return (
    <div aria-hidden className="overflow-hidden rounded-card border border-border bg-surface shadow-card">
      <ul className="divide-y divide-border">
        {Array.from({ length: rows }).map((_, i) => (
          <li key={i} className={DATA_ROW}>
            {leading && <div className="skeleton size-9 shrink-0 rounded-control" />}
            <div className="min-w-0 flex-1 space-y-2">
              <div className="skeleton h-3.5" style={{ width: `${34 + ((i * 19) % 36)}%` }} />
              <div className="skeleton h-3 w-1/2" />
            </div>
            <div className="skeleton hidden h-5 w-24 rounded-full sm:block" />
          </li>
        ))}
      </ul>
    </div>
  );
}
