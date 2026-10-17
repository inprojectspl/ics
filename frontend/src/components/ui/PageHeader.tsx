import type { ReactNode } from "react";
import { clsx } from "clsx";

interface Props {
  title: ReactNode;
  /** One line under the title: a count, the role in a project. Not a paragraph of help. */
  description?: ReactNode;
  /** Primary action (and at most a secondary one) of the view. */
  actions?: ReactNode;
  /** Leading visual, e.g. a project monogram. */
  leading?: ReactNode;
  className?: string;
}

/**
 * The single heading of a view: its `h1`, one supporting line and the
 * primary action. Everything else the view can do goes to `PageToolbar`
 * or the `…` menu, so the title always wins the first glance.
 */
export function PageHeader({ title, description, actions, leading, className }: Props) {
  return (
    <header
      className={clsx(
        "flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end sm:justify-between sm:gap-x-6",
        className ?? "mb-6",
      )}
    >
      <div className="flex min-w-0 items-center gap-3 sm:flex-[1_1_20rem]">
        {leading}
        <div className="min-w-0">
          <h1 className="text-heading font-semibold text-text-primary [overflow-wrap:anywhere]">{title}</h1>
          {description && <p className="mt-1 text-body text-text-secondary">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}
