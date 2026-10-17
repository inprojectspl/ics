import { useEffect, useRef, type ReactNode } from "react";
import { Download } from "lucide-react";
import { hydrateMarkdown, type CollectionContext } from "../lib/hydrateMarkdown";
import { fillIcsLinkTitles } from "../lib/icsLinkTitles";
import { t } from "../lib/i18n";
import { mountWidgets, repaintForTheme } from "../lib/mountWidgets";
import { mt } from "../styles/markdown-theme";
import type { Theme } from "../lib/theme";

interface Props {
  html: string;
  theme: Theme;
  title?: string | null;
  subtitle?: string | null;
  meta?: string | null;
  collection?: CollectionContext | null;
  /** When provided, renders a download-source icon next to the title.
   * For md_single this is the document itself; for vault files we leave
   * it out - vault-wide download lives in the sidebar instead. */
  downloadHref?: string;
  /** Accessible name of the download link, "download source" by default. */
  downloadLabel?: string;
  /** Notes shown between the title and the body (e.g. security findings). */
  children?: ReactNode;
  /** Called with the hydrated body after each render (table of contents). */
  onRendered?: (root: HTMLElement) => void;
}

/**
 * Self-contained reader. Parses HTML only when `html` changes; re-paints
 * (shiki/mermaid) when `theme` changes without touching the DOM tree.
 */
export function MarkdownView({
  html,
  theme,
  title,
  subtitle,
  meta,
  collection,
  downloadHref,
  downloadLabel = t("markdownView.downloadSource"),
  children,
  onRendered,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const themeRef = useRef<Theme>(theme);
  const onRenderedRef = useRef(onRendered);
  useEffect(() => {
    onRenderedRef.current = onRendered;
  });
  // Declared before the hydration effect so it runs first in the same commit.
  useEffect(() => {
    themeRef.current = theme;
  }, [theme]);

  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    root.innerHTML = html;
    hydrateMarkdown(root, collection ?? null);
    onRenderedRef.current?.(root);
    void mountWidgets(root, { theme: themeRef.current });
    let stale = false;
    void fillIcsLinkTitles(root, () => stale);
    return () => {
      stale = true;
    };
  }, [html, collection]);

  useEffect(() => {
    const root = ref.current;
    if (!root || !root.innerHTML) return;
    void repaintForTheme(root, theme);
  }, [theme]);

  // A body that opens with its own <h1> already has a title; the chrome title
  // above it would be a near-duplicate heading (the breadcrumb still shows it).
  const bodyHasLeadingH1 = /^\s*<h1[\s>]/i.test(html);
  const showChromeTitle = Boolean(title) && !bodyHasLeadingH1;

  return (
    // .md-container is a size container (container-type in theme.css) spanning
    // the available width; wide-element breakout computes max-width in cqw,
    // so it respects the reader inspector.
    <div className="md-container">
      <article className={mt.prose}>
        {/* Header row: meta overline (left) + download (right). Always present
            so the download stays reachable even when the chrome title is
            suppressed in favour of the document's own H1. */}
        {(meta || downloadHref) && (
          <div className="flex items-start justify-between gap-4">
            {meta ? <div className={mt.meta}>{meta}</div> : <span aria-hidden />}
            {downloadHref && (
              <a
                href={downloadHref}
                download
                aria-label={downloadLabel}
                title={downloadLabel}
                className="shrink-0 -mt-1 inline-flex items-center justify-center w-9 h-9 rounded-control text-text-tertiary hover:text-text-primary hover:bg-surface-subtle transition-colors"
              >
                <Download size={18} aria-hidden />
              </a>
            )}
          </div>
        )}
        {showChromeTitle && (
          <h1 className={((title as string).length > 60 ? mt.titleSmall : mt.title) + " has-anchor"}>
            {title}
          </h1>
        )}
        {subtitle && <p className={mt.subtitle}>{subtitle}</p>}
        {children}
        <div ref={ref} className="markdown-body" />
      </article>
    </div>
  );
}
