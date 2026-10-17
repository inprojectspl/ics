/** Canvas 2D drawing for the graph engine. */
import { getInitialTheme } from "../../lib/theme";
import { radiusOf } from "./simulation";
import type { RenderSettings, SimEdge, SimNode, Size, Transform } from "./types";

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

/** Theme colours the canvas draws with. */
export interface Palette {
  inkSoft: string;
  rule: string;
  accent: string;
  ink: string;
  paper: string;
  inkMute: string;
  paperRaised: string;
  paperSunk: string;
  warn: string;
  /** The ICS mark's orange, for decorative nodes (the sign-in backdrop). */
  brand: string;
  /** Dark theme: badge text and shadows pick their dark variants. */
  dark: boolean;
}

export const PALETTE_FALLBACK: Palette = {
  inkSoft: "#666",
  rule: "#ccc",
  accent: "#c95b17",
  ink: "#222",
  paper: "#fff",
  inkMute: "#999",
  paperRaised: "#fff",
  paperSunk: "#f4f4f4",
  warn: "#d9a33a",
  brand: "#ff5500",
  dark: false,
};



const DASH = [4, 3];
const LABEL_FONT = '11px "Mona Sans", system-ui, sans-serif';
const LABEL_FONT_HOVER = '13px "Mona Sans", system-ui, sans-serif';

/**
 * Resolves the theme colours in one `getComputedStyle` call, which forces a
 * style recalc; callers read it once and again only on a theme change.
 */
export function readPalette(): Palette {
  if (typeof document === "undefined") return PALETTE_FALLBACK;
  const cs = getComputedStyle(document.body);
  const pick = (name: string, fallback: string): string =>
    cs.getPropertyValue(name).trim() || fallback;
  return {
    inkSoft: pick("--color-text-secondary", PALETTE_FALLBACK.inkSoft),
    rule: pick("--color-border", PALETTE_FALLBACK.rule),
    accent: pick("--color-accent", PALETTE_FALLBACK.accent),
    ink: pick("--color-text-primary", PALETTE_FALLBACK.ink),
    paper: pick("--color-surface", PALETTE_FALLBACK.paper),
    inkMute: pick("--color-text-tertiary", PALETTE_FALLBACK.inkMute),
    paperRaised: pick("--color-surface", PALETTE_FALLBACK.paperRaised),
    paperSunk: pick("--color-surface-subtle", PALETTE_FALLBACK.paperSunk),
    warn: pick("--color-warning", PALETTE_FALLBACK.warn),
    brand: pick("--color-brand-mark", PALETTE_FALLBACK.brand),
    dark: getInitialTheme() === "dark",
  };
}

/**
 * Edges touching the hovered node and the nodes at their far ends, in one
 * pass: both sets are needed per frame.
 */
export function hoverFocus(
  edges: SimEdge[],
  hover: number | null,
): { edges: Set<number>; nodes: Set<number> } {
  const focusEdges = new Set<number>();
  const focusNodes = new Set<number>();
  if (hover == null) return { edges: focusEdges, nodes: focusNodes };
  for (let i = 0; i < edges.length; i++) {
    const e = edges[i];
    if (!e) continue;
    if (e.fromIdx === hover || e.toIdx === hover) {
      focusEdges.add(i);
      focusNodes.add(e.fromIdx);
      focusNodes.add(e.toIdx);
    }
  }
  return { edges: focusEdges, nodes: focusNodes };
}

/**
 * Label policy:
 *   `always`: every node visible at zoom > 0.6
 *   `hover` : hovered + current, plus neighbours (or all when nothing is
 *             hovered) at high zoom
 *   `off`   : never (current still shown)
 */
export function shouldShowLabel(
  labels: RenderSettings["labels"],
  zoom: number,
  state: { isHover: boolean; isCurrent: boolean; isNbr: boolean; anyHover: boolean },
): boolean {
  if (labels === "off") return state.isCurrent;
  if (labels === "always") return zoom > 0.6;
  return (
    state.isHover || state.isCurrent || (zoom > 0.85 && (state.isNbr || !state.anyHover))
  );
}

export interface DrawArgs {
  canvas: HTMLCanvasElement;
  nodes: SimNode[];
  edges: SimEdge[];
  size: Size;
  transform: Transform;
  settings: RenderSettings;
  hoverIdx: number | null;
  /** Id of the node drawn as current (accent fill, label always shown). */
  currentId: string | undefined;
  /** Omitted: resolved per frame, which costs a style recalc. */
  palette?: Palette;
}

/** Renders one frame to the given canvas. */
export function drawScene(args: DrawArgs): void {
  const { canvas, nodes, edges, size, transform: t, settings: cfg } = args;
  const { hoverIdx: hover, currentId } = args;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const { w, h } = size;
  ctx.clearRect(0, 0, w, h);
  ctx.save();
  ctx.translate(t.x, t.y);
  ctx.scale(t.zoom, t.zoom);

  const focus = hoverFocus(edges, hover);
  const { inkSoft, rule: ruleColor, accent, ink, paper, inkMute } =
    args.palette ?? readPalette();

  // Edges first so nodes draw on top. Endpoints are pulled back to
  // the node circumference (not the centre) so arrows don't end up
  // hidden under the target dot.
  for (let edgeIdx = 0; edgeIdx < edges.length; edgeIdx++) {
    const e = edges[edgeIdx];
    if (!e) continue;
    const a = nodes[e.fromIdx];
    const b = nodes[e.toIdx];
    if (!a || !b) continue;
    const style = e.style;
    const focused = focus.edges.has(edgeIdx) || style?.highlighted === true;
    const dim = (hover != null && !focus.edges.has(edgeIdx)) || style?.faded === true;
    // Edges are faint so the graph reads as a mesh. Focused edges (neighbours of
    // the hovered node) stand out; dimmed ones (hover elsewhere) nearly vanish.
    const color = focused ? accent : (style?.color ?? ruleColor);
    ctx.strokeStyle = color;
    ctx.globalAlpha = dim ? 0.12 : focused ? 0.85 : 0.35;

    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
    const ux = dx / dist;
    const uy = dy / dist;
    const rA = radiusOf(a, cfg.nodeScale);
    const rB = radiusOf(b, cfg.nodeScale);
    const x1 = a.x + ux * rA;
    const y1 = a.y + uy * rA;
    const x2 = b.x - ux * rB;
    const y2 = b.y - uy * rB;

    ctx.lineWidth = style?.width ?? 1;
    if (style?.dashed) ctx.setLineDash(DASH);
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
    if (style?.dashed) ctx.setLineDash([]);

    if (cfg.showArrows) {
      const ah = 6; // arrowhead length
      const aw = 3; // arrowhead half-width
      // Perpendicular to the edge direction.
      const px = -uy;
      const py = ux;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.moveTo(x2, y2);
      ctx.lineTo(x2 - ux * ah + px * aw, y2 - uy * ah + py * aw);
      ctx.lineTo(x2 - ux * ah - px * aw, y2 - uy * ah - py * aw);
      ctx.closePath();
      ctx.fill();
    }
  }
  ctx.globalAlpha = 1;

  const hovered = hover != null ? hover : -1;
  // Font changes re-parse the CSS font string; set it only when the size changes.
  let font = "";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  for (let nodeIdx = 0; nodeIdx < nodes.length; nodeIdx++) {
    const n = nodes[nodeIdx];
    if (!n) continue;
    const style = n.style;
    const r = radiusOf(n, cfg.nodeScale);
    const isHover = nodeIdx === hovered;
    const isNbr = focus.nodes.has(nodeIdx);
    const isCurrent = (currentId != null && n.id === currentId) || style?.highlighted === true;
    const dim = (hover != null && !isHover && !isNbr) || style?.faded === true;
    ctx.beginPath();
    ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
    ctx.fillStyle =
      isCurrent || isHover ? accent : isNbr ? ink : (style?.color ?? inkSoft);
    ctx.globalAlpha = dim ? 0.3 : 1;
    ctx.fill();
    ctx.lineWidth = isHover ? 2.5 : 1.5;
    ctx.strokeStyle = style?.border ?? paper;
    if (style?.dashed) ctx.setLineDash(DASH);
    ctx.stroke();
    if (style?.dashed) ctx.setLineDash([]);
    const showLabel = shouldShowLabel(cfg.labels, t.zoom, {
      isHover,
      isCurrent,
      isNbr,
      anyHover: hover != null,
    });
    if (showLabel) {
      ctx.globalAlpha = dim ? 0.35 : 1;
      ctx.fillStyle = isHover || isCurrent ? ink : inkMute;
      const want = isHover ? LABEL_FONT_HOVER : LABEL_FONT;
      if (font !== want) {
        ctx.font = want;
        font = want;
      }
      ctx.fillText(truncate(n.label, isHover ? 60 : 30), n.x, n.y + r + 4);
    }
  }
  ctx.globalAlpha = 1;
  ctx.restore();
}
