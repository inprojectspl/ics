import { useId, useRef, type ReactNode } from "react";
import { clsx } from "clsx";
import { ChevronRight } from "lucide-react";
import { useEnterMotion } from "../../lib/motion";

interface Props {
  /** Leading column (an icon tile, a time); the panel lines up after it. */
  leading: ReactNode;
  /** What the row says while closed. */
  header: ReactNode;
  /** Shown under the header while open. */
  children: ReactNode;
  open: boolean;
  onToggle: () => void;
  /** `li` inside a `DataList`, `div` inside a virtualized list. */
  as?: "li" | "div";
  align?: "center" | "start";
  dense?: boolean;
  className?: string;
}

/**
 * A list row that opens in place to show the record behind it. Columns are
 * a subgrid, so the panel aligns with any leading content without
 * hand-computed insets.
 */
export function ExpandableRow({
  leading,
  header,
  children,
  open,
  onToggle,
  as: Tag = "li",
  align = "center",
  dense = false,
  className,
}: Props) {
  const panelId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  useEnterMotion(panelRef, "reveal", open);
  const start = align === "start";

  return (
    <Tag className={clsx("grid grid-cols-[auto_minmax(0,1fr)_auto]", className)}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={onToggle}
        className={clsx(
          "col-span-3 grid grid-cols-subgrid text-left transition-colors duration-150 hover:bg-surface-hover",
          start ? "items-start" : "items-center",
          dense ? "py-2.5" : "py-3",
        )}
      >
        <span className="flex items-start gap-3 pl-3 pr-3 sm:pl-4 sm:pr-4">{leading}</span>
        <span className="min-w-0">{header}</span>
        <ChevronRight
          size={16}
          aria-hidden
          className={clsx(
            "mx-3 shrink-0 text-text-secondary transition-transform duration-150 ease-standard sm:mr-4",
            start && "mt-0.5",
            open && "rotate-90",
          )}
        />
      </button>
      {open && (
        <div ref={panelRef} id={panelId} className="col-span-3 grid grid-cols-subgrid border-t border-border bg-surface-subtle py-3">
          <div className="col-span-3 min-w-0 px-3 sm:col-span-1 sm:col-start-2 sm:px-0">{children}</div>
        </div>
      )}
    </Tag>
  );
}
