import { type ReactNode } from "react";
import { clsx } from "clsx";

interface Option<T extends string> {
  value: T;
  label: string;
  icon?: ReactNode;
  tooltip?: string;
}

interface Props<T extends string> {
  value: T;
  onChange: (v: T) => void;
  options: Option<T>[];
  ariaLabel: string;
}

/**
 * Segmented control: one of a few views or modes (text or graph, all or
 * unread, theme). A sunk track with the chosen segment raised, so the
 * choice reads without relying on colour.
 */
export function SegmentedToggle<T extends string>({
  value,
  onChange,
  options,
  ariaLabel,
}: Props<T>) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className="inline-flex max-w-full items-center rounded-control bg-surface-subtle p-0.5 ring-1 ring-inset ring-border"
    >
      {options.map((o) => {
        const active = value === o.value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(o.value)}
            title={o.tooltip}
            className={clsx(
              "inline-flex h-7 items-center gap-1.5 whitespace-nowrap rounded-[calc(var(--radius-control)-2px)] px-2.5",
              "text-ui transition-[color,background-color] duration-150 ease-standard",
              active
                ? "bg-surface font-medium text-text-primary shadow-card ring-1 ring-border"
                : "text-text-secondary hover:text-text-primary",
            )}
          >
            {o.icon}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
