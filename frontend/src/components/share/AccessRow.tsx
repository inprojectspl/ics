import type { ReactNode } from "react";

/** One grant in a share list: who or what, its role, and the way to undo it. */
export function AccessRow({
  title,
  detail,
  badge,
  actions,
  muted = false,
}: {
  title: ReactNode;
  detail?: ReactNode;
  badge?: ReactNode;
  actions?: ReactNode;
  muted?: boolean;
}) {
  return (
    <li className={muted ? "flex items-center gap-3 px-3 py-2.5 opacity-55" : "flex items-center gap-3 px-3 py-2.5"}>
      <div className="min-w-0 flex-1">
        <div className="truncate text-ui font-medium text-text-primary">{title}</div>
        {detail && <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-meta text-text-secondary">{detail}</div>}
      </div>
      {badge}
      {actions && <div className="flex shrink-0 items-center gap-1">{actions}</div>}
    </li>
  );
}

/** Bordered list of `AccessRow`s. */
export function AccessList({ label, children }: { label: string; children: ReactNode }) {
  return (
    <ul aria-label={label} className="divide-y divide-border overflow-hidden rounded-card border border-border">
      {children}
    </ul>
  );
}
