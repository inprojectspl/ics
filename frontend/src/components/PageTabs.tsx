import { clsx } from "clsx";
import { AppLink } from "./ui/AppLink";
import { BLEED_SCROLL } from "./ui/bleed";

interface PageTab {
  key: string;
  href: string;
  label: string;
}

interface Props {
  tabs: readonly PageTab[];
  active: string;
  ariaLabel: string;
  className?: string;
}

/** Local tabs between the sections of one object (a project, the account
 * settings). Links, so each section has its own address; never a copy of
 * the sidebar. */
export function PageTabs({ tabs, active, ariaLabel, className }: Props) {
  return (
    <nav aria-label={ariaLabel} className={clsx(BLEED_SCROLL, className)}>
      <ul className="flex min-w-max gap-1 border-b border-border">
        {tabs.map((x) => {
          const current = x.key === active;
          return (
            <li key={x.key}>
              <AppLink
                href={x.href}
                aria-current={current ? "page" : undefined}
                className={clsx(
                  "relative inline-flex h-10 items-center whitespace-nowrap px-3 text-ui transition-colors duration-150",
                  current ? "font-medium text-text-primary" : "text-text-secondary hover:text-text-primary",
                )}
              >
                {x.label}
                <span
                  aria-hidden
                  className={clsx("absolute inset-x-3 -bottom-px h-0.5 rounded-full", current ? "bg-accent" : "bg-transparent")}
                />
              </AppLink>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
