/** Loading list with the geometry of `DocumentRow` (icon, title, summary,
 * metadata), so the swap to real rows never moves the page. */
export function AssetListSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div aria-hidden className="overflow-hidden rounded-card border border-border bg-surface shadow-card">
      <ul className="divide-y divide-border">
        {Array.from({ length: rows }).map((_, i) => (
          <li key={i} className="flex items-start gap-3 px-3 py-3 sm:gap-4 sm:px-4">
            <div className="skeleton mt-0.5 size-9 shrink-0 rounded-control" />
            <div className="min-w-0 flex-1 space-y-2 py-0.5">
              <div className="skeleton h-3.5" style={{ width: `${40 + ((i * 17) % 38)}%` }} />
              <div className="skeleton h-3 w-3/4" />
              <div className="skeleton h-2.5 w-52" />
            </div>
            <div className="skeleton hidden h-5 w-20 self-center rounded-full sm:block" />
          </li>
        ))}
      </ul>
    </div>
  );
}
