import type { ReactNode } from "react";
import { clsx } from "clsx";

interface Props {
  /** Finding: search in the view, filters. */
  start?: ReactNode;
  /** Arranging: sort, view mode, the `…` of the view. */
  end?: ReactNode;
  /** Active filter chips, shown as a second row only when there are any. */
  chips?: ReactNode;
  className?: string;
}

/**
 * The one row of controls of a view, directly above its data. On a phone
 * the search takes the first line (give it `basis-full sm:basis-auto`)
 * and the rest shares the second.
 */
export function PageToolbar({ start, end, chips, className }: Props) {
  return (
    <div className={clsx("flex flex-col gap-2", className)}>
      <div role="toolbar" className="flex flex-wrap items-center gap-2">
        {start}
        {end && <div className="ml-auto flex shrink-0 items-center gap-1.5">{end}</div>}
      </div>
      {chips}
    </div>
  );
}
