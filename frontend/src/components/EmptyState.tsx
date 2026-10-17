import { clsx } from "clsx";
import { type LucideIcon } from "lucide-react";
import { type ReactNode } from "react";

interface Props {
  icon: LucideIcon;
  title: string;
  description?: ReactNode;
  /** What the person can do about it: clear the filters, retry. Never the
   * page's own primary action, which the header already offers. */
  action?: ReactNode;
  className?: string;
  /** Inside a bordered surface (a list container) instead of on the canvas. */
  framed?: boolean;
  /** One line for an empty section of a page, not the whole view. */
  compact?: boolean;
}

/** Empty, zero or no-access state: says what is going on and what to do next. */
export function EmptyState({ icon: Icon, title, description, action, className, framed = true, compact = false }: Props) {
  if (compact) {
    return (
      <div className={clsx("flex items-start gap-3 px-4 py-4", framed && "rounded-card border border-dashed border-border-strong bg-surface", className)}>
        <Icon size={18} aria-hidden className="mt-0.5 shrink-0 text-text-secondary" />
        <div className="min-w-0">
          <p className="text-ui font-medium text-text-primary">{title}</p>
          {description && <p className="mt-0.5 text-ui text-text-secondary">{description}</p>}
        </div>
      </div>
    );
  }
  return (
    <div
      className={clsx(
        "flex flex-col items-center justify-center px-6 py-14 text-center",
        framed && "rounded-card border border-dashed border-border-strong bg-surface",
        className,
      )}
    >
      <span aria-hidden className="mb-4 inline-flex size-12 items-center justify-center rounded-full bg-surface-subtle text-text-secondary">
        <Icon size={22} strokeWidth={1.6} />
      </span>
      <p className="text-body font-semibold text-text-primary">{title}</p>
      {description && <p className="mt-1 max-w-md text-ui text-text-secondary">{description}</p>}
      {action && <div className="mt-5 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  );
}
