import type { ReactNode } from "react";
import { clsx } from "clsx";

/**
 * One surface for a collection, rows split by hairlines: the list pattern
 * of documents, projects, members and admin tables. No card per row and no
 * shadow per row; the container carries the one frame.
 */
export function DataList({
  children,
  className,
  label,
}: {
  children: ReactNode;
  className?: string;
  /** Accessible name of the list. */
  label?: string;
}) {
  return (
    <div className={clsx("overflow-hidden rounded-card border border-border bg-surface shadow-card", className)}>
      <ul aria-label={label} className="divide-y divide-border">
        {children}
      </ul>
    </div>
  );
}

/**
 * Row padding shared by every `DataList`, one utility per property so rows
 * never override it. `interactive` rows light up on hover; `align: "start"`
 * keeps a tall row's leading and trailing columns at the top.
 */
export function dataRow({
  interactive = true,
  align = "center",
}: { interactive?: boolean; align?: "center" | "start" } = {}): string {
  return clsx(
    "group/row relative flex gap-3 px-3 py-3 sm:gap-4 sm:px-4",
    align === "start" ? "items-start" : "items-center",
    interactive && "transition-colors duration-150 hover:bg-surface-subtle",
  );
}

export const DATA_ROW = dataRow();
