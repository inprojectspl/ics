/**
 * Tailwind classes per markdown element, applied by hydrateMarkdown() so
 * backend-rendered HTML needs no class attributes. Tokens are in theme.css.
 */

import { clsx } from "clsx";

/** Class for wrappers that may extend beyond the text column (theme.css
 * `.markdown-body > .md-breakout`); new widgets opt in by adding it. */
export const MD_BREAKOUT = "md-breakout";

export const mt = {
  /* ===== Container ===== */
  prose: clsx(
    "font-reading text-text-primary text-prose",
    "max-w-(--reading-width) mx-auto",
    "px-(--gutter) pt-8 pb-16 sm:pt-12",
    "selection:bg-accent-soft selection:text-text-primary",
  ),

  /* ===== Document chrome (set in MarkdownView, not auto-applied) ===== */
  title: clsx(
    "font-ui text-display font-semibold text-text-primary",
    "mt-0 mb-3",
    "[font-variation-settings:'opsz'_60,'wght'_500]",
    // text-pretty keeps nice line balancing; break-words +
    // overflow-wrap:anywhere break long titles without spaces (e.g. an
    // Asset.title renamed to one very long word) so they do not overflow the
    // mobile viewport.
    "text-pretty break-words [overflow-wrap:anywhere]",
  ),
  titleSmall: clsx(
    "font-ui text-h1 font-semibold text-text-primary",
    "mt-0 mb-3",
    "[font-variation-settings:'opsz'_36,'wght'_600]",
    "text-pretty break-words [overflow-wrap:anywhere]",
  ),
  subtitle: clsx(
    "font-ui text-lead text-text-secondary mb-12 mt-0",
    "[font-variation-settings:'opsz'_18,'wght'_400]",
    "text-balance",
  ),
  meta: "font-ui text-meta text-text-secondary mb-2",

  /* ===== Headings (rendered inside .prose by hydrateMarkdown) ===== */
  h1: clsx(
    "font-ui text-h1 font-semibold text-text-primary",
    "[font-variation-settings:'opsz'_28,'wght'_600]",
    "mt-14 mb-4 first:mt-0",
    "scroll-mt-32 text-pretty",
  ),
  h2: clsx(
    "font-ui text-h2 font-semibold text-text-primary",
    "[font-variation-settings:'opsz'_24,'wght'_600]",
    "mt-12 mb-3",
    "scroll-mt-32 text-pretty",
  ),
  h3: clsx(
    "font-ui text-h3 font-semibold text-text-primary",
    "[font-variation-settings:'opsz'_20,'wght'_600]",
    "mt-10 mb-2 scroll-mt-32 text-pretty",
  ),
  h4: clsx(
    "font-ui text-h4 font-semibold text-text-primary",
    "mt-8 mb-2 scroll-mt-32",
  ),
  h5: "font-ui text-body font-semibold text-text-primary mt-6 mb-1",
  h6: "font-ui text-ui font-semibold text-text-secondary mt-6 mb-1",

  /* Anchor link beside headings (added by hydrateMarkdown) */
  headingAnchor: clsx(
    "ml-2 text-text-tertiary no-underline opacity-0 group-hover:opacity-100",
    "transition-opacity text-[0.6em] font-ui font-normal",
    "hover:text-accent",
  ),

  /* ===== Body ===== */
  p: clsx(
    "my-5",
    "[font-variation-settings:'opsz'_8]",
    // A token longer than the column (a hash, a URL) wraps instead of
    // widening the page on a phone.
    "text-pretty break-words",
  ),
  // Lede paragraph - opt-in via data-lede="true" on first <p>
  pLede: clsx(
    "text-lead mb-8 mt-0 text-text-primary",
    "[font-variation-settings:'opsz'_10,'wght'_400]",
  ),

  strong: "font-semibold text-text-primary",
  em: "italic",
  del: "line-through text-text-tertiary decoration-text-tertiary",

  /* ===== Links ===== */
  a: clsx(
    "text-accent underline decoration-accent/30 decoration-from-font underline-offset-[3px]",
    "hover:decoration-accent transition-[text-decoration-color] duration-150",
    "break-words",
  ),

  /* External link icon - added by hydrateMarkdown when href starts with http */
  externalIcon: "inline-block w-3 h-3 ml-0.5 align-baseline text-text-tertiary",

  /* ===== Lists ===== */
  ul: "list-disc marker:text-text-tertiary pl-6 my-5 space-y-2",
  ol: "list-decimal marker:text-text-tertiary pl-6 my-5 space-y-2",
  li: "pl-1 break-words",
  /* task-list-item: styles are in theme.css (flex here split inline
     children into separate items, breaking `**Label** value` into two
     columns). */
  liTask: "task-list-item-row",

  /* ===== Tables =====
     `w-full` with auto layout wraps cells instead of pushing columns off
     screen; `.table-wrap` scrolls only unbreakable content. No
     `hyphens:auto`: it splits words at syllables. */
  tableWrap: "my-8 overflow-x-auto rounded-control border border-border",
  table: "w-full font-ui text-ui border-collapse",
  thead: "bg-surface-subtle",
  th: clsx(
    "text-left font-semibold text-meta",
    "px-4 py-2.5 text-text-secondary border-b border-border",
  ),
  td: clsx(
    "px-4 py-3 border-b border-border align-top",
    // Auto-layout (w-full) splits 100% of the column between columns;
    // overflow-wrap breaks long words/tokens so a cell does not widen the table.
    "[overflow-wrap:break-word]",
  ),
  tbodyTr: "hover:bg-surface-subtle/40 transition-colors",

  /* ===== Code ===== */
  codeInline: clsx(
    "font-code text-[0.92em] px-1.5 py-0.5 rounded-xs",
    "bg-code-inline text-code-ink",
    "border border-border/40",
  ),
  // Code block container (lazy-shiki target)
  codeBlock: clsx(
    "group relative my-8 rounded-control overflow-hidden border border-border",
    "bg-code-bg",
  ),
  codeBlockHeader: clsx(
    "flex items-center justify-between px-4 py-2",
    "border-b border-border/60 bg-surface-subtle/40",
    "font-ui text-meta text-text-secondary",
  ),
  codeLang: "font-code",
  codeCopyBtn: clsx(
    "inline-flex items-center gap-1 px-2 py-0.5 rounded-xs",
    "text-text-tertiary hover:text-text-primary hover:bg-surface-subtle transition-colors",
    "focus-visible:opacity-100",
  ),
  codeContent: clsx(
    "font-code text-ui text-code-ink",
    "p-5 overflow-x-auto leading-[1.7]",
  ),

  /* ===== Blockquote (pull-quote style, not a left bar) ===== */
  blockquote: clsx(
    "my-10 px-8 py-2",
    "italic text-text-secondary",
    "border-l-2 border-border-strong",
    "[&>p]:my-3",
  ),

  /* ===== Horizontal rule (thin line) =====
     A ::before ornament does not render here: Tailwind preflight sets
     `hr { height: 0 }` and the UA stylesheet sets `overflow: hidden`, so the
     pseudo-element gets clipped to zero. `h-px` + `bg-border` paints the box
     itself, so it survives both rules. */
  hr: "my-10 h-px border-0 bg-border",

  /* ===== Image & figure ===== */
  figure: "my-10 group",
  img: "rounded-control w-full max-w-full",
  figcaption: clsx(
    "mt-3 font-ui text-meta text-text-secondary text-center",
  ),

  /* ===== Mark / highlight ===== */
  mark: "bg-accent-soft text-text-primary px-0.5 rounded-xs",

  /* Task list checkbox styling (applied by hydrateMarkdown) */
  taskCheckbox: "mr-2 accent-accent translate-y-[1px]",

  /* ===== Callouts (Obsidian-style) =====
     Structural slots and per-type colorways are split, which keeps the
     indexed `variants` typed against CalloutType. */
  callout: {
    base: clsx(
      "my-8 rounded-control border px-5 py-4",
      "[&>*:first-child]:mt-0 [&>*:last-child]:mb-0",
    ),
    titleRow: "flex items-center gap-2 mb-2",
    title: "font-ui font-semibold text-ui",
    icon: "w-4 h-4 shrink-0",
    body: "text-[0.95em] text-text-primary",
    variants: {
      note:     "bg-surface-subtle border-border [&_.callout-title]:text-text-secondary",
      info:     "bg-info/[0.06] border-info/30 [&_.callout-title]:text-info [&_.callout-icon]:text-info",
      tip:      "bg-success/[0.06] border-success/30 [&_.callout-title]:text-success [&_.callout-icon]:text-success",
      success:  "bg-success/[0.06] border-success/30 [&_.callout-title]:text-success [&_.callout-icon]:text-success",
      question: "bg-info/[0.06] border-info/30 [&_.callout-title]:text-info [&_.callout-icon]:text-info",
      warning:  "bg-warning/[0.08] border-warning/40 [&_.callout-title]:text-warning [&_.callout-icon]:text-warning",
      failure:  "bg-danger/[0.06] border-danger/30 [&_.callout-title]:text-danger [&_.callout-icon]:text-danger",
      danger:   "bg-danger/[0.10] border-danger/50 [&_.callout-title]:text-danger [&_.callout-icon]:text-danger",
      bug:      "bg-danger/[0.06] border-danger/30 [&_.callout-title]:text-danger [&_.callout-icon]:text-danger",
      example:  "bg-quote/[0.06] border-quote/30 [&_.callout-title]:text-quote [&_.callout-icon]:text-quote",
      quote:    "bg-surface-subtle border-border italic [&_.callout-title]:text-text-secondary",
    },
  },

  /* ===== Mermaid ===== */
  // Figure + viewport + pan/zoom controls, see lib/mermaid.ts.
  // Figure: frame + reserved height (no CLS). overflow-hidden keeps the
  // unrendered source and a zoomed diagram contained, so the page does not
  // scroll horizontally before the lazy render. `group` drives control
  // visibility on hover.
  mermaidFigure: clsx(
    "group relative my-10 p-4 bg-surface rounded-control border border-border",
    "overflow-hidden",
  ),
  // Pan/zoom surface: panzoom transforms the inner <svg>, the viewport clips
  // it. min-h reserves space before the SVG appears.
  mermaidViewport: clsx(
    "relative overflow-hidden rounded-control min-h-[160px]",
    "flex items-center justify-center",
    "[&_svg]:max-w-full [&_svg]:h-auto [&_svg]:select-none",
  ),
  // +/-/reset controls: on desktop they appear on figure hover/focus; on
  // touch (coarse pointer) they are always visible, since there is no hover.
  mermaidControls: clsx(
    "absolute top-2 right-2 z-10 flex gap-1",
    "opacity-0 transition-opacity",
    "group-hover:opacity-100 group-focus-within:opacity-100",
    "[@media(pointer:coarse)]:opacity-100",
  ),
  mermaidButton: clsx(
    "grid place-items-center h-8 w-8 rounded-control cursor-pointer",
    "bg-surface/90 border border-border text-text-primary shadow-card backdrop-blur-sm",
    "hover:bg-surface active:scale-95 transition",
    "focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent",
  ),
  mermaidLoading: "font-ui text-text-secondary text-meta",
  mermaidError: clsx(
    "my-10 p-4 bg-danger/10 border border-danger/30 rounded-control",
    "font-code text-ui text-danger",
  ),

  /* ===== Math (KaTeX) ===== */
  mathBlock: "my-8 py-4 overflow-x-auto text-text-primary",
  mathInline: "text-text-primary",

  /* ===== Video / iframe embed ===== */
  videoWrapper: clsx(
    "my-10 aspect-video bg-surface-subtle rounded-control overflow-hidden",
    "border border-border",
  ),
  videoIframe: "w-full h-full border-0",
  videoNative: "w-full h-full object-contain bg-surface-subtle",

  /* ===== Audio ===== */
  audio: "w-full my-6 rounded-control",

  /* ===== Footnotes ===== */
  footnotes: clsx(
    "mt-20 pt-8 border-t border-border",
    "text-ui text-text-secondary",
    "[&_ol]:list-decimal [&_ol]:pl-6 [&_li]:my-2",
  ),
  footnotesHeader: "font-ui text-meta font-semibold text-text-secondary mb-4",
  footnoteRef: clsx(
    "text-accent no-underline align-super text-[0.7em] ml-0.5",
    "hover:underline",
  ),
  footnoteBackref: "ml-1 text-text-tertiary no-underline hover:text-accent",

  /* ===== Definition list ===== */
  dl: "my-6",
  dt: "font-ui font-semibold text-text-primary mt-4",
  dd: "ml-6 my-1 text-text-secondary",

  /* ===== Keyboard / sample ===== */
  kbd: clsx(
    "font-code text-meta px-1.5 py-0.5 rounded-xs",
    "bg-surface-subtle border border-border shadow-[0_1px_0_var(--color-border)]",
    "text-text-primary",
  ),

  /* ===== Tag (Obsidian #tag) ===== */
  tag: clsx(
    "inline-flex items-center font-ui text-meta",
    "px-2 py-0.5 rounded-full",
    "bg-accent-soft text-accent",
    "hover:bg-accent/10 transition-colors no-underline",
  ),

  /* ===== Wikilink ===== */
  // Colour only, no underline: a dotted decoration breaks up at heading
  // sizes, and the accent colour is affordance enough against body text.
  wikilink: "text-accent hover:text-accent/80 transition-colors",
  wikilinkBroken: "text-text-tertiary italic line-through decoration-text-tertiary/40",

  /* ===== Misc ===== */
  details: clsx(
    "my-6 rounded-control border border-border bg-surface-subtle/40",
    "[&[open]>summary]:border-b [&[open]>summary]:border-border [&[open]>summary]:mb-3",
  ),
  summary: clsx(
    "px-4 py-3 font-ui font-medium cursor-pointer",
    "hover:bg-surface-subtle transition-colors",
    "marker:text-text-tertiary",
  ),
  detailsBody: "px-4 pb-4",
} as const;

/**
 * Per-tag map used by hydrateMarkdown to apply classes to backend HTML.
 * Keep ordering deterministic for tests.
 */
export const tagClassMap: Record<string, string> = {
  h1: mt.h1,
  h2: mt.h2,
  h3: mt.h3,
  h4: mt.h4,
  h5: mt.h5,
  h6: mt.h6,
  p: mt.p,
  strong: mt.strong,
  em: mt.em,
  del: mt.del,
  a: mt.a,
  ul: mt.ul,
  ol: mt.ol,
  li: mt.li,
  table: mt.table,
  thead: mt.thead,
  th: mt.th,
  td: mt.td,
  blockquote: mt.blockquote,
  hr: mt.hr,
  figure: mt.figure,
  img: mt.img,
  figcaption: mt.figcaption,
  mark: mt.mark,
  kbd: mt.kbd,
  dl: mt.dl,
  dt: mt.dt,
  dd: mt.dd,
  details: mt.details,
  summary: mt.summary,
  audio: mt.audio,
};
