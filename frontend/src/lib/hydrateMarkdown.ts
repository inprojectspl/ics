/**
 * Styles and decorates backend-rendered HTML in place (theme classes,
 * callouts, code blocks, headings, footnotes, links, table wrappers).
 * Mermaid and KaTeX are mounted later by `mountWidgets`.
 */

import { CALLOUT_ICON, CalloutType, isCalloutType } from "../styles/callouts";
import { t } from "./i18n";
import { decorateMermaid } from "./mermaid";
import { MD_BREAKOUT, mt, tagClassMap } from "../styles/markdown-theme";

const HEADING_TAGS = new Set(["H1", "H2", "H3", "H4", "H5", "H6"]);

// Romanization for Polish letters, some of which (like the stroked l) don't
// decompose into combining diacritics under NFKD. Without this map those
// letters get stripped from the slug instead of mapped to their ASCII base.
const PL_MAP: Record<string, string> = {
  ą: "a", ć: "c", ę: "e", ł: "l", ń: "n", ó: "o", ś: "s", ź: "z", ż: "z",
};

function addClass(el: Element, cls: string): void {
  if (!cls) return;
  el.classList.add(...cls.split(/\s+/).filter(Boolean));
}

function isExternal(href: string): boolean {
  try {
    const u = new URL(href, window.location.href);
    return u.origin !== window.location.origin && /^https?:$/.test(u.protocol);
  } catch {
    return false;
  }
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[ąćęłńóśźż]/g, (c) => PL_MAP[c] || c)
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}

function applyTagClasses(root: HTMLElement): void {
  root.querySelectorAll<HTMLElement>("*").forEach((el) => {
    const tag = el.tagName.toLowerCase();
    const cls = tagClassMap[tag];
    if (cls) addClass(el, cls);
  });
}

function decorateLinks(root: HTMLElement): void {
  root.querySelectorAll<HTMLAnchorElement>("a[href]").forEach((a) => {
    const href = a.getAttribute("href") || "";
    if (isExternal(href)) {
      a.setAttribute("target", "_blank");
      a.setAttribute("rel", "noopener noreferrer");
      if (!a.querySelector(".ext-icon")) {
        const icon = document.createElement("span");
        icon.className = "ext-icon " + mt.externalIcon;
        icon.setAttribute("aria-hidden", "true");
        icon.textContent = "↗";
        a.appendChild(icon);
      }
    }
  });
}

function decorateHeadings(root: HTMLElement): void {
  const seen = new Map<string, number>();
  root.querySelectorAll<HTMLElement>("h1,h2,h3,h4,h5,h6").forEach((h) => {
    if (!HEADING_TAGS.has(h.tagName)) return;
    h.classList.add("group");

    let id = h.id || slugify(h.textContent || "");
    if (!id) return;
    const n = seen.get(id) ?? 0;
    seen.set(id, n + 1);
    if (n > 0) id = `${id}-${n}`;
    h.id = id;

    if (!h.querySelector(".heading-anchor")) {
      const a = document.createElement("a");
      a.href = `#${id}`;
      a.className = "heading-anchor " + mt.headingAnchor;
      a.setAttribute("aria-label", t("markdown.headingAnchor"));
      a.textContent = "§";
      h.appendChild(a);
    }
  });
}

function wrapTables(root: HTMLElement): void {
  root.querySelectorAll<HTMLTableElement>("table").forEach((table) => {
    if (table.parentElement?.classList.contains("table-wrap")) return;
    const wrap = document.createElement("div");
    wrap.className = "table-wrap " + mt.tableWrap;
    // Tables get no breakout: they keep the text column width and wrap cells
    // (`table: w-full`). At breakout width (1280px) they look too wide next to
    // the text and hide right-hand columns behind a scroll. Breakout is
    // for code, video and mermaid; overflow-x-auto on `.table-wrap` is the
    // safety net for unbreakable content.
    table.replaceWith(wrap);
    wrap.appendChild(table);
  });
}

/**
 * Adds .kv-table to two-column `| **Label** | value |` tables (theme.css sizes
 * the label column to its content). Deliberately strict: every first <td> must
 * hold a <strong> covering at least 70% of its text, which rules out numbered
 * tables, matrices and two-column tables without bold labels.
 */
function markKeyValueTables(root: HTMLElement): void {
  root.querySelectorAll<HTMLTableElement>("table").forEach((table) => {
    if (table.classList.contains("kv-table")) return;
    const bodyRows = Array.from(table.querySelectorAll<HTMLTableRowElement>("tbody > tr"));
    if (bodyRows.length < 2) return;

    for (const tr of bodyRows) {
      const cells = tr.querySelectorAll(":scope > td");
      if (cells.length !== 2) return;
      const firstTd = cells[0] as HTMLTableCellElement;
      const strong = firstTd.querySelector("strong");
      if (!strong) return;
      const tdText = (firstTd.textContent ?? "").trim();
      const strongText = (strong.textContent ?? "").trim();
      if (tdText.length === 0) return;
      // Strong must cover at least 70% of the cell text, which filters out
      // emphasis mid-sentence (`| plain **bold** inside | val |`).
      if (strongText.length < tdText.length * 0.7) return;
    }

    table.classList.add("kv-table");
  });
}

function decorateCallouts(root: HTMLElement): void {
  root.querySelectorAll<HTMLElement>("aside[data-callout]").forEach((el) => {
    const raw = el.dataset.callout || "note";
    const type: CalloutType = isCalloutType(raw) ? raw : "note";
    addClass(el, mt.callout.base);
    addClass(el, mt.callout.variants[type]);

    const titleRow = el.querySelector(".callout-title-row");
    if (titleRow) addClass(titleRow as HTMLElement, mt.callout.titleRow);
    const title = el.querySelector(".callout-title");
    if (title) addClass(title as HTMLElement, mt.callout.title);
    const body = el.querySelector(".callout-body");
    if (body) addClass(body as HTMLElement, mt.callout.body);
    const icon = el.querySelector(".callout-icon");
    if (icon) {
      addClass(icon as HTMLElement, mt.callout.icon);
      icon.setAttribute("data-lucide", CALLOUT_ICON[type]);
    }
  });
}

function decorateTaskItems(root: HTMLElement): void {
  root.querySelectorAll<HTMLElement>("li.task-list-item").forEach((li) => {
    addClass(li, mt.liTask);
    const input = li.querySelector("input[type='checkbox']");
    if (input) {
      addClass(input as HTMLElement, mt.taskCheckbox);
      (input as HTMLInputElement).disabled = true;
    }
  });
}

function decorateCodeBlocks(root: HTMLElement): void {
  root.querySelectorAll<HTMLElement>("pre[data-widget='code']").forEach((pre) => {
    if (pre.parentElement?.classList.contains("code-figure")) return;
    const lang = pre.dataset.lang || "";
    const figure = document.createElement("div");
    figure.className = `code-figure ${MD_BREAKOUT} ` + mt.codeBlock;

    const header = document.createElement("div");
    header.className = mt.codeBlockHeader;

    const langLabel = document.createElement("span");
    langLabel.className = mt.codeLang;
    langLabel.textContent = lang || "code";

    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "code-copy " + mt.codeCopyBtn;
    copyBtn.textContent = t("markdown.copy");
    copyBtn.setAttribute("aria-label", t("markdown.copyAria"));

    header.appendChild(langLabel);
    header.appendChild(copyBtn);

    const codeWrap = document.createElement("div");
    codeWrap.className = mt.codeContent;

    pre.replaceWith(figure);
    figure.appendChild(header);
    figure.appendChild(codeWrap);
    codeWrap.appendChild(pre);
    pre.className = ""; // shiki will repaint
    pre.style.margin = "0";
  });
}

function decorateMath(root: HTMLElement): void {
  root.querySelectorAll<HTMLElement>(".math.block, .math.inline").forEach((el) => {
    if (el.classList.contains("block")) {
      addClass(el, mt.mathBlock);
      el.setAttribute("data-widget", "math-block");
    } else {
      addClass(el, mt.mathInline);
      el.setAttribute("data-widget", "math-inline");
    }
  });
}

function wrapVideoEmbeds(root: HTMLElement): void {
  root.querySelectorAll<HTMLIFrameElement>("iframe").forEach((iframe) => {
    if (iframe.parentElement?.classList.contains("video-wrap")) return;
    const wrap = document.createElement("div");
    wrap.className = `video-wrap ${MD_BREAKOUT} ` + mt.videoWrapper;
    addClass(iframe, mt.videoIframe);
    iframe.replaceWith(wrap);
    wrap.appendChild(iframe);
  });
  root.querySelectorAll<HTMLVideoElement>("video").forEach((v) => {
    if (v.parentElement?.classList.contains("video-wrap")) return;
    const wrap = document.createElement("div");
    wrap.className = `video-wrap ${MD_BREAKOUT} ` + mt.videoWrapper;
    addClass(v, mt.videoNative);
    v.replaceWith(wrap);
    wrap.appendChild(v);
  });
}

function decorateFootnotes(root: HTMLElement): void {
  const section = root.querySelector<HTMLElement>("section.footnotes");
  if (!section) return;
  addClass(section, mt.footnotes);
  const header = document.createElement("h2");
  header.className = mt.footnotesHeader;
  header.textContent = t("markdown.footnotes");
  section.insertBefore(header, section.firstChild);
  root.querySelectorAll<HTMLAnchorElement>("a.footnote-ref").forEach((a) => addClass(a, mt.footnoteRef));
  root.querySelectorAll<HTMLAnchorElement>("a.footnote-backref").forEach((a) => addClass(a, mt.footnoteBackref));
}

function makeFirstParagraphLede(root: HTMLElement): void {
  // Lede style for the first paragraph if the document has 3+ paragraphs
  // and there's no heading before it.
  const paragraphs = root.querySelectorAll<HTMLParagraphElement>("p");
  if (paragraphs.length < 3) return;
  const first = paragraphs[0];
  if (!first) return;
  // Skip if it sits inside a callout or blockquote
  if (first.closest("aside,blockquote,li,figure")) return;
  if (first.previousElementSibling) {
    const prev = first.previousElementSibling.tagName;
    if (HEADING_TAGS.has(prev)) return;
  }
  first.classList.remove(...mt.p.split(/\s+/));
  addClass(first, mt.pLede);
}

export interface CollectionContext {
  /** Sorted list of MD-file paths in the collection. */
  paths: string[];
  /** Current file path being viewed (used to scope relative resolutions). */
  current: string;
  /** Build the viewer URL for a target path. */
  hrefFor: (path: string) => string;
}

function resolveWikilink(target: string, ctx: CollectionContext): string | null {
  // Exact path match, with or without `.md` suffix.
  const candidates = [
    target,
    target + ".md",
    target.replace(/^\/+/, "") + ".md",
  ];
  for (const c of candidates) {
    const match = ctx.paths.find((p) => p === c);
    if (match) return match;
  }
  // Filename-only (Obsidian style: [[Page]] resolves to any Page.md in vault).
  const lc = target.toLowerCase().replace(/\.md$/, "");
  const byBasename = ctx.paths.find((p) => {
    const base = p.split("/").pop() ?? p;
    return base.toLowerCase().replace(/\.md$/, "") === lc;
  });
  return byBasename ?? null;
}

function decorateWikilinks(root: HTMLElement, ctx: CollectionContext | null): void {
  root.querySelectorAll<HTMLAnchorElement>("a.wikilink[data-target]").forEach((a) => {
    addClass(a, mt.wikilink);
    const target = a.dataset.target || "";
    if (!ctx) {
      // No collection context: render as broken / placeholder.
      addClass(a, mt.wikilinkBroken);
      a.setAttribute("title", t("markdown.wikilinkNoContext"));
      return;
    }
    const resolved = resolveWikilink(target, ctx);
    if (resolved) {
      a.setAttribute("href", ctx.hrefFor(resolved));
    } else {
      addClass(a, mt.wikilinkBroken);
      a.setAttribute("title", t("markdown.wikilinkNotFound", { target }));
    }
  });
}

/**
 * Apply all hydrations. Pure DOM operations; safe to call multiple times
 * (operations are idempotent via marker classes).
 */
export function hydrateMarkdown(
  root: HTMLElement,
  ctx: CollectionContext | null = null,
): void {
  applyTagClasses(root);
  markKeyValueTables(root);
  wrapTables(root);
  decorateCallouts(root);
  decorateTaskItems(root);
  decorateCodeBlocks(root);
  decorateMermaid(root);
  decorateMath(root);
  wrapVideoEmbeds(root);
  decorateHeadings(root);
  decorateLinks(root);
  decorateWikilinks(root, ctx);
  decorateFootnotes(root);
  makeFirstParagraphLede(root);
  decorateImages(root);
}

function decorateImages(root: HTMLElement): void {
  // `loading="lazy"` defers off-screen hi-res images, which matters for long
  // notes full of screenshots. `decoding="async"` keeps PNG decoding from
  // blocking paint. Native attributes (95%+ support per caniuse) that are
  // simply ignored where unsupported.
  root.querySelectorAll<HTMLImageElement>("img").forEach((img) => {
    if (!img.hasAttribute("loading")) img.loading = "lazy";
    if (!img.hasAttribute("decoding")) img.decoding = "async";
  });
}
