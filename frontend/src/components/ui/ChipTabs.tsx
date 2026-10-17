import { clsx } from "clsx";
import { BLEED_SCROLL } from "./bleed";

interface ChipTab<K extends string> {
  key: K;
  label: string;
  count?: number;
}

interface Props<K extends string> {
  label: string;
  items: readonly ChipTab<K>[];
  active: K;
  onChange: (key: K) => void;
  className?: string;
}

/**
 * Mutually exclusive views of one list, each with its count: status queues
 * (users, upkeep lists). A count above zero is set in bold so the work is
 * visible before anything is opened. Scrolls sideways on a phone.
 */
export function ChipTabs<K extends string>({ label, items, active, onChange, className }: Props<K>) {
  return (
    <nav aria-label={label} className={clsx(BLEED_SCROLL, className)}>
      <ul className="flex min-w-max gap-1.5 sm:min-w-0 sm:flex-wrap">
        {items.map((it) => {
          const on = it.key === active;
          return (
            <li key={it.key}>
              <button
                type="button"
                aria-current={on ? "true" : undefined}
                onClick={() => onChange(it.key)}
                className={clsx(
                  "inline-flex h-8 items-center gap-2 rounded-full border px-3 text-ui transition-colors duration-150",
                  on
                    ? "border-accent bg-accent-soft font-medium text-text-primary"
                    : "border-border bg-surface text-text-secondary hover:bg-surface-hover hover:text-text-primary",
                )}
              >
                {it.label}
                {it.count !== undefined && (
                  <span className={clsx("text-meta tabular-nums", it.count > 0 ? "font-semibold text-text-primary" : "text-text-tertiary")}>
                    {it.count}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
