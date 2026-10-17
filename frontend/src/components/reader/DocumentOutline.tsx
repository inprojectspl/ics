import { useEffect, useState } from "react";
import { clsx } from "clsx";
import { t } from "../../lib/i18n";
import type { OutlineEntry } from "./outline";

interface Props {
  entries: readonly OutlineEntry[];
  /** Called after a jump, so a drawer can close and uncover the text. */
  onJump?: () => void;
}

/**
 * Table of contents of the open document. The section being read is marked
 * as the page scrolls; a click jumps to it and moves focus there, so
 * keyboard and screen reader users land where they asked to go.
 */
export function DocumentOutline({ entries, onJump }: Props) {
  const [current, setCurrent] = useState<string | null>(null);

  useEffect(() => {
    if (entries.length === 0 || typeof IntersectionObserver === "undefined") return;
    const nodes = entries.map((e) => document.getElementById(e.id)).filter((n): n is HTMLElement => Boolean(n));
    const observer = new IntersectionObserver(
      (seen) => {
        const top = seen.filter((s) => s.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (top) setCurrent(top.target.id);
      },
      // The band under the bars where a heading counts as "being read".
      { rootMargin: "-120px 0px -65% 0px" },
    );
    for (const n of nodes) observer.observe(n);
    return () => observer.disconnect();
  }, [entries]);

  if (entries.length === 0) return <p className="px-1 text-ui text-text-secondary">{t("reader.outlineEmpty")}</p>;

  return (
    <nav aria-label={t("reader.outline")}>
      <ol className="space-y-0.5 border-l border-border">
        {entries.map((e) => {
          const active = e.id === current;
          return (
            <li key={e.id}>
              <a
                href={`#${e.id}`}
                aria-current={active ? "location" : undefined}
                onClick={(ev) => {
                  const target = document.getElementById(e.id);
                  if (!target) return;
                  ev.preventDefault();
                  target.scrollIntoView({ block: "start" });
                  target.setAttribute("tabindex", "-1");
                  target.focus({ preventScroll: true });
                  window.history.replaceState(null, "", `#${e.id}`);
                  setCurrent(e.id);
                  onJump?.();
                }}
                className={clsx(
                  "-ml-px block border-l-2 py-1 pr-2 text-ui transition-colors duration-150",
                  e.level === 3 ? "pl-6" : "pl-3",
                  active
                    ? "border-accent font-medium text-text-primary"
                    : "border-transparent text-text-secondary hover:border-border-strong hover:text-text-primary",
                )}
              >
                <span className="line-clamp-2">{e.text}</span>
              </a>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
