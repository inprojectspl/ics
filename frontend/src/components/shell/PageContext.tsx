import { useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { t } from "../../lib/i18n";
import { AppLink } from "../ui/AppLink";
import { useShell } from "./shellContext";

export interface Crumb {
  label: string;
  /** Link target; leave out for the current location and structural segments. */
  href?: string;
}

interface Props {
  /** Path from the module to here; the last entry is the current location. */
  crumbs?: readonly Crumb[];
  /** A few actions tied to this location that the view toolbar does not have. */
  actions?: ReactNode;
  /** Sidebar entry to mark active, when the address alone cannot tell. */
  activeHref?: string | null;
}

/**
 * Where the page is: renders the breadcrumb bar under the global bar (a
 * portal into the shell's slot) and tells the sidebar which entry to mark.
 * A page without hierarchy renders none, and the bar takes no space.
 */
export function PageContext({ crumbs, actions, activeHref }: Props) {
  const { contextSlot, setActiveHref } = useShell();
  useEffect(() => {
    if (activeHref === undefined) return;
    setActiveHref(activeHref);
    return () => setActiveHref(null);
  }, [activeHref, setActiveHref]);

  if (!crumbs?.length && !actions) return null;
  const bar = <ContextBar crumbs={crumbs ?? []} actions={actions} />;
  return contextSlot ? createPortal(bar, contextSlot) : bar;
}

function ContextBar({ crumbs, actions }: { crumbs: readonly Crumb[]; actions?: ReactNode }) {
  const last = crumbs.length - 1;
  const parent = crumbs.slice(0, last).reverse().find((c) => c.href);
  const current = crumbs[last];
  return (
    <div className="flex h-10 items-center gap-3 border-b border-border bg-canvas px-(--gutter)">
      <nav aria-label={t("chrome.breadcrumbs")} className="min-w-0 flex-1">
        {/* Phones: the way up and where you are, nothing in between. */}
        <div className="flex min-w-0 items-center gap-1 text-ui sm:hidden">
          {parent?.href && (
            <AppLink
              href={parent.href}
              className="-ml-1 inline-flex max-w-[45%] shrink-0 items-center gap-0.5 rounded-control px-1 py-1 text-text-secondary hover:text-text-primary"
            >
              <ChevronLeft size={16} aria-hidden className="shrink-0" />
              <span className="truncate">{parent.label}</span>
            </AppLink>
          )}
          {current && (
            <span aria-current="page" className="min-w-0 truncate font-medium text-text-primary">
              {parent && <span className="sr-only">/ </span>}
              {current.label}
            </span>
          )}
        </div>
        <ol className="hidden min-w-0 items-center gap-1 text-ui sm:flex">
          {crumbs.map((c, i) => (
            <li key={`${i}:${c.label}`} className={i === last ? "min-w-0 flex-1" : "flex min-w-0 max-w-[16rem] shrink items-center gap-1"}>
              {i === last ? (
                <span aria-current="page" className="block truncate font-medium text-text-primary" title={c.label}>
                  {c.label}
                </span>
              ) : (
                <>
                  {c.href ? (
                    <AppLink href={c.href} className="truncate rounded-xs text-text-secondary hover:text-text-primary" title={c.label}>
                      {c.label}
                    </AppLink>
                  ) : (
                    <span className="truncate text-text-secondary" title={c.label}>
                      {c.label}
                    </span>
                  )}
                  <ChevronRight size={14} aria-hidden className="shrink-0 text-text-tertiary" />
                </>
              )}
            </li>
          ))}
        </ol>
      </nav>
      {actions && <div className="flex shrink-0 items-center gap-1">{actions}</div>}
    </div>
  );
}
