/**
 * Mermaid in two phases. `decorateMermaid()` runs before paint and wraps the
 * source in a clipped, height-reserving figure (no overflow, no layout shift).
 * `mountMermaid()` renders lazily near the viewport and adds pan/zoom;
 * @panzoom/panzoom is imported dynamically because this module is eager.
 */

import type { PanzoomObject } from "@panzoom/panzoom";
import { t } from "./i18n";
import { observeOnce } from "./lazyObserve";
import { MD_BREAKOUT, mt } from "../styles/markdown-theme";

type Theme = "light" | "dark";

const FIGURE_CLASS = "mermaid-figure";

// Deterministic id counter (instead of Date.now) so tests are stable.
let renderSeq = 0;

// Panzoom factory cache: fetched once per session.
let panzoomFactory: typeof import("@panzoom/panzoom").default | null = null;

// Mermaid module cache. Imported on the first intersection (not as soon as
// the figure exists in the DOM) so a diagram below the fold does not pull
// the heavy chunk until the user scrolls to it.
let mermaidPromise: Promise<typeof import("mermaid").default> | null = null;

async function getMermaid(): Promise<typeof import("mermaid").default> {
  if (!mermaidPromise) mermaidPromise = import("mermaid").then((m) => m.default);
  return mermaidPromise;
}

/**
 * Phase 1: wraps `<pre class="mermaid">` in a container that reserves space.
 * Idempotent (marked by `.mermaid-figure`). The raw `<pre>` stays as a hidden
 * source carrier, needed for the render and for repaint on theme change.
 */
export function decorateMermaid(root: HTMLElement): void {
  root.querySelectorAll<HTMLElement>("pre.mermaid[data-widget='mermaid']").forEach((pre) => {
    if (pre.closest(`.${FIGURE_CLASS}`)) return; // already wrapped

    const figure = document.createElement("figure");
    figure.className = `${FIGURE_CLASS} ${MD_BREAKOUT} ` + mt.mermaidFigure;
    figure.setAttribute("role", "group");
    figure.setAttribute("aria-label", t("mermaid.figure"));

    const viewport = document.createElement("div");
    viewport.className = "mermaid-viewport " + mt.mermaidViewport;

    const skeleton = document.createElement("div");
    skeleton.className = "mermaid-skeleton " + mt.mermaidLoading;
    skeleton.textContent = t("mermaid.rendering");

    pre.hidden = true; // hidden source carrier

    pre.replaceWith(figure);
    viewport.appendChild(pre);
    viewport.appendChild(skeleton);
    figure.appendChild(viewport);
  });
}

function makeButton(label: string, aria: string, onClick: () => void): HTMLButtonElement {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "mermaid-btn " + mt.mermaidButton;
  b.textContent = label;
  b.setAttribute("aria-label", aria);
  b.addEventListener("click", (e) => {
    e.preventDefault();
    onClick();
  });
  return b;
}

async function getPanzoom(): Promise<typeof import("@panzoom/panzoom").default> {
  if (!panzoomFactory) {
    const mod = await import("@panzoom/panzoom");
    panzoomFactory = mod.default;
  }
  return panzoomFactory;
}

async function setupPanzoom(
  figure: HTMLElement,
  viewport: HTMLElement,
  svg: SVGElement,
): Promise<void> {
  const Panzoom = await getPanzoom();
  const pz: PanzoomObject = Panzoom(svg as unknown as HTMLElement, {
    maxScale: 6,
    minScale: 0.5,
    step: 0.4,
    // No `contain`: "outside" raises the minimum scale until the diagram
    // covers the viewport, which crops wide, short diagrams on first render.
    // Pan only when zoomed in: at scale=1 a one-finger gesture belongs to
    // the page (touchAction: pan-y), so article scrolling on mobile does not
    // get stuck on the diagram. Pinch (2 fingers) always zooms.
    panOnlyWhenZoomed: true,
    touchAction: "pan-y",
    cursor: "grab",
  });

  // Mouse wheel zooms to the cursor (panzoom calls preventDefault itself).
  viewport.addEventListener("wheel", pz.zoomWithWheel);

  const controls = document.createElement("div");
  controls.className = "mermaid-controls " + mt.mermaidControls;
  controls.appendChild(makeButton("+", t("mermaid.zoomIn"), () => void pz.zoomIn()));
  controls.appendChild(makeButton("−", t("mermaid.zoomOut"), () => void pz.zoomOut()));
  controls.appendChild(makeButton("⤢", t("mermaid.fit"), () => void pz.reset()));
  figure.appendChild(controls);
}

function initMermaid(mermaid: typeof import("mermaid").default, theme: Theme): void {
  mermaid.initialize({
    startOnLoad: false,
    theme: theme === "dark" ? "dark" : "default",
    fontFamily: "var(--font-ui), sans-serif",
    securityLevel: "strict",
  });
}

async function renderFigure(figure: HTMLElement, theme: Theme): Promise<void> {
  const pre = figure.querySelector<HTMLElement>("pre.mermaid");
  const viewport = figure.querySelector<HTMLElement>(".mermaid-viewport");
  if (!pre || !viewport) return;

  const src = (pre.textContent || "").trim();
  try {
    const mermaid = await getMermaid();
    initMermaid(mermaid, theme);
    const { svg } = await mermaid.render(`mermaid-render-${renderSeq++}`, src);
    const tmp = document.createElement("div");
    tmp.innerHTML = svg;
    const svgEl = tmp.querySelector("svg");
    if (!svgEl) throw new Error("renderer returned no SVG");

    svgEl.style.maxWidth = "100%";
    svgEl.style.height = "auto";

    // Drop the previous render/skeleton but keep the hidden source <pre>.
    viewport.querySelectorAll(".mermaid-skeleton, svg").forEach((n) => n.remove());
    viewport.appendChild(svgEl);

    await setupPanzoom(figure, viewport, svgEl);
    // data-theme is the only marker: its presence means "rendered" and its
    // value tells which theme (source of truth for repaint).
    figure.dataset.theme = theme;
  } catch (err) {
    figure.className = mt.mermaidError;
    figure.textContent = t("mermaid.renderError", { error: String(err) });
  }
}

/**
 * Phase 2: lazy render. Mermaid + panzoom are fetched on the figure's first
 * intersection (via the shared observeOnce), so an off-screen diagram costs
 * no bytes until the user reaches it.
 */
export function mountMermaid(root: HTMLElement, theme: Theme): void {
  root.querySelectorAll<HTMLElement>(`figure.${FIGURE_CLASS}`).forEach((figure) => {
    if (figure.dataset.theme) return; // already rendered
    observeOnce(figure, () => void renderFigure(figure, theme));
  });
}

/**
 * Re-renders already rendered figures after a theme change, from the source
 * in the hidden `<pre>`. Figures render in parallel; panzoom is initialised
 * again on the fresh SVG.
 */
export async function repaintMermaid(root: HTMLElement, theme: Theme): Promise<void> {
  const figures = Array.from(
    root.querySelectorAll<HTMLElement>(`figure.${FIGURE_CLASS}[data-theme]`),
  ).filter((f) => f.dataset.theme !== theme);
  if (figures.length === 0) return;

  await Promise.all(
    figures.map((figure) => {
      figure.querySelectorAll(".mermaid-controls").forEach((c) => c.remove());
      return renderFigure(figure, theme);
    }),
  );
}
