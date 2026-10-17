import type { ReactNode } from "react";
import { clsx } from "clsx";

/** A titled block of a side panel (the reader inspector, the map panel).
 * Blocks are split by hairlines, not boxed. */
export function PanelSection({
  title,
  aside,
  children,
  last = false,
}: {
  title: string;
  /** Right end of the title row: a count, a small action. */
  aside?: ReactNode;
  children: ReactNode;
  last?: boolean;
}) {
  return (
    <section className={clsx(!last && "mb-4 border-b border-border pb-4")}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="text-meta font-semibold text-text-secondary">{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

const ROW =
  "flex min-h-9 w-full items-center gap-2.5 rounded-control px-2 py-1.5 text-left text-ui " +
  "text-text-primary transition-colors duration-150 hover:bg-surface-hover";

/** An action row of a panel; same look whether it is a button or a download link. */
export function PanelAction({
  icon,
  label,
  title,
  onClick,
  danger = false,
  disabled = false,
}: {
  icon: ReactNode;
  label: string;
  title?: string;
  onClick: () => void;
  danger?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      disabled={disabled}
      className={clsx(ROW, danger && "text-danger hover:bg-danger-soft", "disabled:cursor-not-allowed disabled:opacity-40")}
    >
      <span className="shrink-0 text-text-secondary">{icon}</span>
      <span className="min-w-0 truncate">{label}</span>
    </button>
  );
}

export function PanelLink({
  href,
  icon,
  label,
  title,
  download = false,
}: {
  href: string;
  icon: ReactNode;
  label: string;
  title?: string;
  download?: boolean;
}) {
  return (
    <a href={href} title={title} {...(download ? { download: "" } : {})} className={ROW}>
      <span className="shrink-0 text-text-secondary">{icon}</span>
      <span className="min-w-0 truncate">{label}</span>
    </a>
  );
}
