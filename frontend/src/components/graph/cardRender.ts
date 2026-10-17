/**
 * Canvas 2D drawing of a card scene. Cards change their level of detail with
 * the zoom: a colour tile far out, a card with its title in the middle, the
 * full card (kicker, badge, title, extra line) close up. Text is sized in
 * screen pixels where it has to stay readable (frame titles, edge labels).
 */
import { drawEdgeLabels } from "./cardLabels";
import { fitText, FONT, isCut, REF_SIZE, roundRect, wrapLines } from "./cardText";
import { FRAME_HEADER, type BadgeTone, type CardScene, type PlacedCard, type RoutedEdge } from "./cardTypes";
import type { Point } from "./interactions";
import type { Palette } from "./render";
import type { Size, Transform } from "./types";

/** Cards and edges kept lit around the hovered or selected card. */
export interface Focus {
  cards: Set<string>;
  edges: Set<number>;
  /** The hovered or selected card itself. */
  centre: string;
}

export function focusOf(scene: CardScene, id: string | null): Focus | null {
  if (id == null) return null;
  const cards = new Set<string>([id]);
  const centre = id;
  const edges = new Set<number>();
  for (const [i, e] of scene.edges.entries()) {
    if (e.source !== id && e.target !== id) continue;
    edges.add(i);
    cards.add(e.source);
    cards.add(e.target);
  }
  return { cards, edges, centre };
}

export interface CardDrawArgs {
  canvas: HTMLCanvasElement;
  scene: CardScene;
  size: Size;
  transform: Transform;
  palette: Palette;
  hoverId: string | null;
  selectedId: string | null;
  focus: Focus | null;
  /** Dotted backdrop that moves with the view. */
  grid?: boolean;
}

/** Zoom from which a card shows its full content. */
const FULL_DETAIL_ZOOM = 0.78;
/** Card height on screen below which a card is only a colour tile. */
const TILE_BELOW = 18;
const RADIUS = 10;
const STRIPE = 5;
const PAD = 16;

function tracePath(ctx: CanvasRenderingContext2D, e: RoutedEdge, down: boolean): void {
  const pts = e.points;
  const first = pts[0];
  if (!first) return;
  ctx.beginPath();
  ctx.moveTo(first.x, first.y);
  if (e.shape === "flow") {
    for (let i = 1; i < pts.length; i++) {
      const p = pts[i - 1];
      const q = pts[i];
      if (!p || !q) continue;
      if (down) {
        const dy = (q.y - p.y) / 2;
        ctx.bezierCurveTo(p.x, p.y + dy, q.x, q.y - dy, q.x, q.y);
      } else {
        const dx = (q.x - p.x) / 2;
        ctx.bezierCurveTo(p.x + dx, p.y, q.x - dx, q.y, q.x, q.y);
      }
    }
  } else if (e.shape === "loop") {
    // Rounded corners, never wider than half of either leg: a narrow channel stays sharp.
    for (let i = 1; i < pts.length - 1; i++) {
      const o = pts[i - 1];
      const p = pts[i];
      const q = pts[i + 1];
      if (!o || !p || !q) continue;
      const r = Math.min(10, Math.hypot(p.x - o.x, p.y - o.y) / 2, Math.hypot(q.x - p.x, q.y - p.y) / 2);
      ctx.arcTo(p.x, p.y, q.x, q.y, r);
    }
    const last = pts[pts.length - 1];
    if (last) ctx.lineTo(last.x, last.y);
  } else {
    const last = pts[pts.length - 1];
    if (last) ctx.lineTo(last.x, last.y);
  }
}

/** Unit direction the edge arrives in at its target end. */
function arrival(e: RoutedEdge, down: boolean): Point {
  const pts = e.points;
  const q = pts[pts.length - 1];
  const p = pts[pts.length - 2];
  if (!p || !q) return { x: 0, y: 1 };
  if (e.shape === "flow") {
    return down ? { x: 0, y: Math.sign(q.y - p.y) || 1 } : { x: Math.sign(q.x - p.x) || 1, y: 0 };
  }
  const len = Math.hypot(q.x - p.x, q.y - p.y) || 1;
  return { x: (q.x - p.x) / len, y: (q.y - p.y) / len };
}

function drawEdges(ctx: CanvasRenderingContext2D, a: CardDrawArgs, lit: boolean): void {
  const { scene, transform: t, palette, focus } = a;
  const down = scene.direction === "down";
  const minW = 1 / t.zoom;
  for (const [i, e] of scene.edges.entries()) {
    const on = focus?.edges.has(i) ?? false;
    if (on !== lit) continue;
    const color = e.color ?? palette.inkMute;
    ctx.globalAlpha = focus ? (on ? 1 : 0.08) : e.quiet ? 0.22 : 0.75;
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = Math.max(e.width, minW) * (on ? 1.9 : 1);
    ctx.setLineDash(e.dashed ? [Math.max(6, 5 / t.zoom), Math.max(4, 3 / t.zoom)] : []);
    tracePath(ctx, e, down);
    ctx.stroke();
    ctx.setLineDash([]);
    const tip = e.points[e.points.length - 1];
    if (!tip) continue;
    const dir = arrival(e, down);
    const len = Math.max(8, 7 / t.zoom) * (on ? 1.15 : 1);
    const half = len * 0.5;
    ctx.beginPath();
    ctx.moveTo(tip.x, tip.y);
    ctx.lineTo(tip.x - dir.x * len - dir.y * half, tip.y - dir.y * len + dir.x * half);
    ctx.lineTo(tip.x - dir.x * len + dir.y * half, tip.y - dir.y * len - dir.x * half);
    ctx.closePath();
    ctx.fill();
  }
  ctx.globalAlpha = 1;
}

function badgeColors(tone: BadgeTone, p: Palette): { bg: string; fg: string } {
  switch (tone) {
    case "warn":
      return { bg: p.dark ? "rgba(251, 191, 36, 0.18)" : "rgba(245, 158, 11, 0.16)", fg: p.dark ? "#fcd34d" : "#92400e" };
    case "info":
      return { bg: p.dark ? "rgba(96, 165, 250, 0.18)" : "rgba(37, 99, 235, 0.1)", fg: p.dark ? "#93c5fd" : "#1e40af" };
    case "mute":
      return { bg: p.dark ? "rgba(148, 163, 184, 0.18)" : "rgba(100, 116, 139, 0.12)", fg: p.inkSoft };
  }
}

/**
 * The left strip of a card cut by its rounded corners: the arcs of the card
 * outline instead of a clip, which would cost a save and restore per card.
 */
function stripePath(ctx: CanvasRenderingContext2D, x: number, y: number, h: number): void {
  const dy = RADIUS - Math.sqrt(RADIUS * RADIUS - (RADIUS - STRIPE) * (RADIUS - STRIPE));
  const top = Math.atan2(dy - RADIUS, STRIPE - RADIUS);
  ctx.beginPath();
  ctx.moveTo(x + STRIPE, y + dy);
  ctx.arc(x + RADIUS, y + RADIUS, RADIUS, top, -Math.PI, true);
  ctx.lineTo(x, y + h - RADIUS);
  ctx.arc(x + RADIUS, y + h - RADIUS, RADIUS, Math.PI, -top, true);
  ctx.closePath();
}

/** Least screen size of a card title; below it the card is drawn as a tile. */
const TITLE_MIN_PX = 6;

/**
 * Size and lines of a card title at middle distance: one size for every card,
 * whatever its line count, so the map reads evenly; up to `maxLines`. Null
 * when the size the card allows is not readable.
 */
function titleLayout(
  ctx: CanvasRenderingContext2D,
  title: string,
  h: number,
  room: number,
  zoom: number,
  screenPx: number,
  maxLines: number,
): { size: number; lines: string[] } | null {
  const size = Math.min(screenPx / Math.max(zoom, 0.01), (h - 12) / (1.22 * maxLines));
  if (size * zoom < TITLE_MIN_PX) return null;
  // Measured at the reference size, so the cache still hits while the zoom changes.
  ctx.font = `600 ${REF_SIZE}px ${FONT}`;
  return { size, lines: wrapLines(ctx, title, (room * REF_SIZE) / size, maxLines) };
}

function strike(ctx: CanvasRenderingContext2D, width: number, x: number, y: number, size: number): void {
  ctx.fillRect(x, y - size * 0.3, width, Math.max(1, size * 0.08));
}

function drawCard(ctx: CanvasRenderingContext2D, c: PlacedCard, a: CardDrawArgs): void {
  const { transform: t, palette: p } = a;
  const density = a.scene.density;
  const selected = c.id === a.selectedId;
  const hovered = c.id === a.hoverId;
  const dim = a.focus != null && !a.focus.cards.has(c.id);
  const px = 1 / t.zoom;
  const task = c.variant === "task";
  ctx.globalAlpha = (dim ? 0.26 : 1) * (c.muted && !selected ? 0.6 : 1);

  if (selected) {
    roundRect(ctx, c.x - 4 * px, c.y - 4 * px, c.w + 8 * px, c.h + 8 * px, RADIUS + 4 * px);
    ctx.strokeStyle = p.accent;
    ctx.lineWidth = 2.5 * px;
    ctx.stroke();
  }

  // Too small for a readable title: a colour tile says more than an empty card.
  const x0 = c.x + PAD;
  const inner = c.w - PAD - 12;
  const middle = t.zoom < FULL_DETAIL_ZOOM || density === "compact";
  const hs = c.h * t.zoom;
  const title =
    middle && hs >= TILE_BELOW
      ? titleLayout(ctx, c.title, c.h, inner - (c.badge ? 10 : 0), t.zoom, density === "compact" ? 13 : 12.5, density === "compact" ? 2 : 3)
      : null;
  if (hs < TILE_BELOW || (middle && !title)) {
    roundRect(ctx, c.x, c.y, c.w, c.h, 5);
    ctx.fillStyle = task ? p.inkMute : c.color;
    ctx.fill();
    ctx.globalAlpha = 1;
    return;
  }

  roundRect(ctx, c.x, c.y, c.w, c.h, RADIUS);
  ctx.fillStyle = task ? p.paperSunk : p.paperRaised;
  ctx.fill();
  ctx.lineWidth = (hovered || selected ? 1.5 : 1) * px;
  ctx.strokeStyle = hovered || selected ? p.accent : p.rule;
  if (c.dashed || task) ctx.setLineDash([5 * px, 3.5 * px]);
  ctx.stroke();
  ctx.setLineDash([]);
  if (!task) {
    stripePath(ctx, c.x, c.y, c.h);
    ctx.fillStyle = c.color;
    ctx.fill();
  }

  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";

  if (middle) {
    if (title) {
      const { size, lines } = title;
      const k = REF_SIZE / size;
      const widths = c.muted ? lines.map((l) => ctx.measureText(l).width / k) : [];
      ctx.font = `600 ${size}px ${FONT}`;
      ctx.fillStyle = p.ink;
      const lead = size * 1.22;
      let y = c.y + c.h / 2 + size * 0.36 - ((lines.length - 1) * lead) / 2;
      for (const [i, line] of lines.entries()) {
        ctx.fillText(line, x0, y);
        if (c.muted) strike(ctx, widths[i] ?? 0, x0, y, size);
        y += lead;
      }
    }
    if (c.badge) {
      ctx.beginPath();
      ctx.arc(c.x + c.w - 11, c.y + 11, Math.max(3.5, 3 * px), 0, Math.PI * 2);
      ctx.fillStyle = c.badge.tone === "warn" ? p.warn : p.inkMute;
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    return;
  }

  // Close up: kicker line with the badge, the title, the extra line.
  let badgeW = 0;
  if (c.badge) {
    ctx.font = `600 10px ${FONT}`;
    const bw = ctx.measureText(c.badge.text).width + 12;
    const bx = c.x + c.w - 10 - bw;
    const colors = badgeColors(c.badge.tone, p);
    roundRect(ctx, bx, c.y + 9, bw, 17, 8.5);
    ctx.fillStyle = colors.bg;
    ctx.fill();
    ctx.fillStyle = colors.fg;
    ctx.fillText(c.badge.text, bx + 6, c.y + 21);
    badgeW = bw + 8;
  }
  if (c.kicker) {
    ctx.font = `600 10px ${FONT}`;
    ctx.letterSpacing = "0.6px";
    ctx.fillStyle = p.inkMute;
    ctx.fillText(fitText(ctx, c.kicker.toUpperCase(), inner - badgeW), x0, c.y + 22);
    ctx.letterSpacing = "0px";
  }
  ctx.font = `600 13.5px ${FONT}`;
  ctx.fillStyle = p.ink;
  let ty = c.y + 42;
  for (const line of wrapLines(ctx, c.title, inner, 3)) {
    ctx.fillText(line, x0, ty);
    if (c.muted) strike(ctx, ctx.measureText(line).width, x0, ty, 13.5);
    ty += 17;
  }
  if (density === "detailed" && c.sub) {
    ctx.font = `400 11.5px ${FONT}`;
    ctx.fillStyle = p.inkMute;
    ctx.fillText(fitText(ctx, c.sub, inner), x0, c.y + c.h - 16);
  }
  ctx.globalAlpha = 1;
}

/** Least screen size a frame title shrinks to before it is cut. */
const FRAME_TITLE_MIN_PX = 9;

function drawFrameTitle(ctx: CanvasRenderingContext2D, f: CardScene["frames"][number], zoom: number, p: Palette): void {
  const x = f.x + 20;
  const room = f.w - 40;
  const count = f.count ? ` · ${f.count}` : "";
  let size = Math.min(13 / zoom, FRAME_HEADER * 0.6);
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  // One line with the count in a quieter tone when it fits.
  ctx.font = `600 ${size}px ${FONT}`;
  const labelW = ctx.measureText(f.label).width;
  ctx.font = `400 ${size}px ${FONT}`;
  const countW = count ? ctx.measureText(count).width : 0;
  const y = f.y + FRAME_HEADER / 2 + 4;
  if (labelW + countW <= room) {
    ctx.font = `600 ${size}px ${FONT}`;
    ctx.fillStyle = p.ink;
    ctx.fillText(f.label, x, y);
    if (count) {
      ctx.font = `400 ${size}px ${FONT}`;
      ctx.fillStyle = p.inkMute;
      ctx.fillText(count, x + labelW, y);
    }
    return;
  }
  // Otherwise two lines in the title strip, smaller if need be, cut only as a last resort.
  size = Math.min(size, (FRAME_HEADER - 10) / 2.4);
  let lines: string[] = [];
  for (; ; size *= 0.9) {
    ctx.font = `600 ${size}px ${FONT}`;
    lines = wrapLines(ctx, f.label + count, room, 2);
    const cut = isCut(lines);
    if (!cut || size * 0.9 * zoom < FRAME_TITLE_MIN_PX) break;
  }
  if (size * zoom < 8) {
    // Far out: one line in a readable size, cut, rather than no name at all.
    size = Math.min(10 / zoom, FRAME_HEADER * 0.7);
    ctx.font = `600 ${size}px ${FONT}`;
    lines = [fitText(ctx, f.label, room)];
  }
  ctx.fillStyle = p.ink;
  const lead = size * 1.2;
  let ly = y - ((lines.length - 1) * lead) / 2;
  for (const line of lines) {
    ctx.fillText(line, x, ly);
    ly += lead;
  }
}

function drawFrames(ctx: CanvasRenderingContext2D, a: CardDrawArgs): void {
  const { scene, transform: t, palette: p } = a;
  for (const f of scene.frames) {
    roundRect(ctx, f.x, f.y, f.w, f.h, 16);
    ctx.fillStyle = p.dark ? "rgba(255, 255, 255, 0.025)" : "rgba(30, 41, 70, 0.025)";
    ctx.fill();
    ctx.lineWidth = 1 / t.zoom;
    ctx.strokeStyle = p.rule;
    ctx.stroke();
    drawFrameTitle(ctx, f, t.zoom, p);
  }
}

let gridTile: { key: string; pattern: CanvasPattern } | null = null;

/** Dot tile for the backdrop, rebuilt only when the spacing or colour changes. */
function gridPattern(ctx: CanvasRenderingContext2D, step: number, color: string): CanvasPattern | null {
  const key = `${step}\u0000${color}`;
  if (gridTile?.key === key) return gridTile.pattern;
  const tile = document.createElement("canvas");
  tile.width = tile.height = step;
  const tctx = tile.getContext("2d");
  if (!tctx) return null;
  tctx.fillStyle = color;
  tctx.fillRect(0, 0, 1.2, 1.2);
  const pattern = ctx.createPattern(tile, "repeat");
  if (pattern) gridTile = { key, pattern };
  return pattern;
}

function drawGrid(ctx: CanvasRenderingContext2D, a: CardDrawArgs): void {
  const { transform: t, size, palette: p } = a;
  let step = 24 * t.zoom;
  while (step < 14) step *= 2;
  step = Math.round(step);
  const pattern = gridPattern(ctx, step, p.rule);
  if (!pattern) return;
  const ox = ((t.x % step) + step) % step;
  const oy = ((t.y % step) + step) % step;
  ctx.save();
  ctx.globalAlpha = p.dark ? 0.55 : 0.8;
  ctx.translate(ox - 0.6, oy - 0.6);
  ctx.fillStyle = pattern;
  ctx.fillRect(-ox, -oy, size.w + step, size.h + step);
  ctx.restore();
}

/** Renders one frame of the scene. */
export function drawCardScene(a: CardDrawArgs): void {
  const ctx = a.canvas.getContext("2d");
  if (!ctx) return;
  const { size, transform: t } = a;
  ctx.clearRect(0, 0, size.w, size.h);
  if (a.grid) drawGrid(ctx, a);
  ctx.save();
  ctx.translate(t.x, t.y);
  ctx.scale(t.zoom, t.zoom);
  drawFrames(ctx, a);
  drawEdges(ctx, a, false);
  // Only cards on screen are drawn; the margin keeps a selection ring whole.
  const left = -t.x / t.zoom - 12;
  const top = -t.y / t.zoom - 12;
  const right = left + size.w / t.zoom + 24;
  const bottom = top + size.h / t.zoom + 24;
  for (const c of a.scene.cards) {
    if (c.x > right || c.y > bottom || c.x + c.w < left || c.y + c.h < top) continue;
    drawCard(ctx, c, a);
  }
  drawEdges(ctx, a, true);
  drawEdgeLabels(ctx, a);
  ctx.restore();
}

/** Topmost card under a world point. */
export function hitCard(scene: CardScene, p: Point): PlacedCard | null {
  for (let i = scene.cards.length - 1; i >= 0; i--) {
    const c = scene.cards[i];
    if (c && p.x >= c.x && p.x <= c.x + c.w && p.y >= c.y && p.y <= c.y + c.h) return c;
  }
  return null;
}
