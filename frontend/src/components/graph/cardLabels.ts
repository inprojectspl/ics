/** Relation labels of the card renderer: where they go and how they are drawn. */
import type { CardDrawArgs } from "./cardRender";
import { FONT, roundRect } from "./cardText";
import { pairKey, type RoutedEdge } from "./cardTypes";
import type { Point } from "./interactions";

/** Middle of a route, where its label goes. */
export function routeMidpoint(points: Point[]): Point {
  const n = points.length;
  if (n === 0) return { x: 0, y: 0 };
  const a = points[Math.floor((n - 1) / 2)] ?? { x: 0, y: 0 };
  const b = points[Math.ceil((n - 1) / 2)] ?? a;
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

function cubicAt(p: Point, q: Point, t: number, down: boolean): Point {
  const u = 1 - t;
  const a = u * u * u;
  const b = 3 * u * u * t;
  const c = 3 * u * t * t;
  const d = t * t * t;
  if (down) {
    const dy = (q.y - p.y) / 2;
    return { x: a * p.x + b * p.x + c * q.x + d * q.x, y: a * p.y + b * (p.y + dy) + c * (q.y - dy) + d * q.y };
  }
  const dx = (q.x - p.x) / 2;
  return { x: a * p.x + b * (p.x + dx) + c * (q.x - dx) + d * q.x, y: a * p.y + b * p.y + c * q.y + d * q.y };
}

/** Point `share` of the way along a route (0 its source end, 1 its target end). */
export function routeAt(e: RoutedEdge, share: number, down: boolean): Point {
  const pts = e.points;
  if (pts.length < 2) return pts[0] ?? { x: 0, y: 0 };
  const lengths: number[] = [];
  let total = 0;
  for (let i = 1; i < pts.length; i++) {
    const p = pts[i - 1];
    const q = pts[i];
    const len = p && q ? Math.hypot(q.x - p.x, q.y - p.y) : 0;
    lengths.push(len);
    total += len;
  }
  let left = Math.min(1, Math.max(0, share)) * total;
  for (const [i, len] of lengths.entries()) {
    const p = pts[i] ?? { x: 0, y: 0 };
    const q = pts[i + 1] ?? p;
    if (left <= len || i === lengths.length - 1) {
      const k = len > 0 ? Math.min(1, left / len) : 0;
      if (e.shape === "flow") return cubicAt(p, q, k, down);
      return { x: p.x + (q.x - p.x) * k, y: p.y + (q.y - p.y) * k };
    }
    left -= len;
  }
  return pts[pts.length - 1] ?? { x: 0, y: 0 };
}

/**
 * Positions tried for a label, as shares of the way from the focused card to
 * its neighbour: past the middle first, so the labels of a busy card fan out
 * with its edges instead of piling up at the card.
 */
const SHARES = [0.6, 0.5, 0.72, 0.4, 0.84, 0.3, 0.92];

/** Where an edge's label goes when nothing is in the way: `share` from `centre`. */
export function labelPoint(e: RoutedEdge, centre: string, share: number, down: boolean): Point {
  return routeAt(e, e.source === centre ? share : 1 - share, down);
}

type Box = { x: number; y: number; w: number; h: number };

const overlaps = (a: Box, b: Box): boolean =>
  a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

export function drawEdgeLabels(ctx: CanvasRenderingContext2D, a: CardDrawArgs): void {
  const { scene, transform: t, palette, focus } = a;
  if (!focus) return;
  const down = scene.direction === "down";
  const font = 11 / t.zoom;
  ctx.font = `600 ${font}px ${FONT}`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  const placed: Box[] = [];
  // A label never covers a card or another label and stays inside the canvas;
  // one with no free spot along its edge is left out.
  const margin = 3 / t.zoom;
  const view: Box = { x: -t.x / t.zoom, y: -t.y / t.zoom, w: a.size.w / t.zoom, h: a.size.h / t.zoom };
  const free = (r: Box) => {
    if (r.x < view.x || r.y < view.y || r.x + r.w > view.x + view.w || r.y + r.h > view.y + view.h) return false;
    const padded = { x: r.x - margin, y: r.y - margin, w: r.w + margin * 2, h: r.h + margin * 2 };
    return !placed.some((o) => overlaps(padded, o)) && !scene.cards.some((c) => overlaps(padded, c));
  };
  // Parallel edges share one label naming every relation between the two cards.
  const groups = new Map<string, { e: RoutedEdge; labels: string[] }>();
  for (const i of focus.edges) {
    const e = scene.edges[i];
    if (!e?.label) continue;
    const key = pairKey(e.source, e.target);
    const group = groups.get(key);
    if (!group) groups.set(key, { e, labels: [e.label] });
    else if (!group.labels.includes(e.label)) group.labels.push(e.label);
  }
  for (const { e, labels } of groups.values()) {
    const text = labels.join(" · ");
    const w = ctx.measureText(text).width + 14 / t.zoom;
    const h = 20 / t.zoom;
    let rect: Box | null = null;
    for (const share of SHARES) {
      const mid = labelPoint(e, focus.centre, share, down);
      const r = { x: mid.x - w / 2, y: mid.y - h / 2, w, h };
      if (free(r)) {
        rect = r;
        break;
      }
    }
    if (!rect) continue;
    placed.push(rect);
    roundRect(ctx, rect.x, rect.y, w, h, h / 2);
    ctx.fillStyle = palette.paperRaised;
    ctx.fill();
    ctx.lineWidth = 1.25 / t.zoom;
    ctx.strokeStyle = e.color ?? palette.inkMute;
    ctx.stroke();
    ctx.fillStyle = palette.ink;
    ctx.fillText(text, rect.x + w / 2, rect.y + h / 2 + 0.5 / t.zoom);
  }
}
