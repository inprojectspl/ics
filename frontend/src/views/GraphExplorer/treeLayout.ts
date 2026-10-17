/**
 * Tidy tree layout of the explored graph, one column (or row) per depth, the
 * parent centred on its children. New children only push later cards along,
 * so cards the reader already saw stay put.
 */
import type {
  CardNode,
  CardScene,
  CardSize,
  Density,
  Direction,
  PlacedCard,
  RoutedEdge,
} from "../../components/graph/cardTypes";
import { FIT_PAD, FOCUS_MIN_ZOOM, TOOLBAR_INSET } from "../../components/graph/cardViewport";
import type { Point } from "../../components/graph/interactions";
import type { ExploredTree, TreeEdge } from "./explorerTree";

/** Space between depths: wide for curves between columns, lower between rows. */
const GAP_X = 96;
const GAP_DOWN = 72;
/** Space between siblings: stacked cards in a column, cards side by side in a row. */
const GAP_Y = 16;
const GAP_SIDE = 20;
/** Extra space between two root subtrees. */
const ROOT_GAP = 40;

export interface TreeLayoutOptions {
  size: CardSize;
  density: Density;
  /** `right`: depth grows to the right; `down`: depth grows downwards. */
  direction?: Direction;
  /** Leaves per line before a wrap, `WRAP` by default; smaller on a small canvas. */
  wrap?: number;
  /** The card for a tree node; edges are styled by `edgeStyle`. */
  card: (id: string) => CardNode;
  edgeStyle: (e: TreeEdge) => Omit<RoutedEdge, "points" | "shape" | "id" | "source" | "target">;
}

/** Most leaves side by side under (or beside) one parent before they wrap into another line. */
export const WRAP = 6;
/** Fewest leaves in a line, even on a phone: one card per line would be a long column again. */
export const MIN_WRAP = 2;
/** Screen space a fit keeps free: padding around and the toolbar strip below. */
const FIT_ROOM = { w: FIT_PAD * 2, h: FIT_PAD * 2 + TOOLBAR_INSET };

/**
 * Leaves per line that still fit the canvas side by side at a readable
 * zoom: across the width when the tree grows down, along the height when
 * it grows right. `WRAP` until the canvas has been measured.
 */
export function wrapFor(direction: Direction, canvas: CardSize, size: CardSize): number {
  if (canvas.w <= 0 || canvas.h <= 0) return WRAP;
  const down = direction === "down";
  const room = (down ? canvas.w - FIT_ROOM.w : canvas.h - FIT_ROOM.h) / FOCUS_MIN_ZOOM;
  const gap = down ? GAP_SIDE : GAP_Y;
  const fits = Math.floor((room + gap) / ((down ? size.w : size.h) + gap));
  return Math.min(WRAP, Math.max(MIN_WRAP, fits));
}

/** Space between two wrapped lines of leaves. */
const LINE_GAP = 24;

/** Top-left corner of every card. */
function placeTree(
  tree: ExploredTree,
  size: CardSize,
  direction: Direction,
  wrap: number = WRAP,
): Map<string, Point> {
  const down = direction === "down";
  // Positions along the depth axis (main) and the sibling axis (cross).
  const main = down ? size.h + GAP_DOWN : size.w + GAP_X;
  const mainSize = down ? size.h : size.w;
  const crossSize = down ? size.w : size.h;
  const gap = down ? GAP_SIDE : GAP_Y;
  const cross = new Map<string, number>();
  /** Offset along the depth axis of a leaf in a wrapped line. */
  const shift = new Map<string, number>();
  const isLeaf = (id: string) => (tree.nodes.get(id)?.children.length ?? 0) === 0;
  // Returns the end of the band the subtree used.
  const place = (id: string, start: number): number => {
    const node = tree.nodes.get(id);
    if (!node) return start;
    const kids = node.children;
    if (kids.length === 0) {
      cross.set(id, start);
      return start + crossSize;
    }
    let end = start;
    const wrapped = kids.length > wrap && kids.every(isLeaf);
    if (wrapped) {
      // Many leaves: a grid of short lines instead of one long one, so the
      // whole neighbourhood fits the screen at a readable size.
      for (const [i, child] of kids.entries()) {
        cross.set(child, start + (i % wrap) * (crossSize + gap));
        shift.set(child, Math.floor(i / wrap) * (mainSize + LINE_GAP));
      }
      end = start + wrap * (crossSize + gap) - gap;
    } else {
      for (const [i, child] of kids.entries()) {
        end = place(child, i === 0 ? start : end + gap);
      }
    }
    const first = cross.get(kids[0] ?? "");
    // Centred on the first line of a grid, which is the whole width of it.
    const last = cross.get(kids[(wrapped ? wrap : kids.length) - 1] ?? "");
    const at = first !== undefined && last !== undefined ? (first + last) / 2 : start;
    cross.set(id, at);
    return Math.max(end, at + crossSize);
  };
  let start = 0;
  for (const root of tree.roots) start = place(root, start) + gap + ROOT_GAP;
  const pos = new Map<string, Point>();
  for (const [id, c] of cross) {
    const depth = (tree.nodes.get(id)?.depth ?? 0) * main + (shift.get(id) ?? 0);
    pos.set(id, down ? { x: c, y: depth } : { x: depth, y: c });
  }
  return pos;
}

/** Middle of the card's side that faces `towards` along the axis: `-1` before it, `1` after. */
function anchor(c: PlacedCard, down: boolean, towards: -1 | 1): Point {
  return down
    ? { x: c.x + c.w / 2, y: towards < 0 ? c.y : c.y + c.h }
    : { x: towards < 0 ? c.x : c.x + c.w, y: c.y + c.h / 2 };
}

/**
 * Route of an edge between two placed cards, from source to target: a
 * curve between the facing sides across depths, a loop through the gap
 * after the line when both sit in the same column (or row).
 */
function route(s: PlacedCard, t: PlacedCard, down: boolean): Pick<RoutedEdge, "points" | "shape"> {
  const at = (c: PlacedCard) => (down ? c.y : c.x);
  if (at(s) === at(t)) {
    const a = anchor(s, down, 1);
    const b = anchor(t, down, 1);
    const lane = (down ? a.y : a.x) + (down ? GAP_DOWN : GAP_X) / 3;
    const bend = (p: Point): Point => (down ? { x: p.x, y: lane } : { x: lane, y: p.y });
    return { shape: "loop", points: [a, bend(a), bend(b), b] };
  }
  const forward = at(s) < at(t) ? 1 : -1;
  return { shape: "flow", points: [anchor(s, down, forward), anchor(t, down, forward === 1 ? -1 : 1)] };
}

export function layoutTree(tree: ExploredTree, o: TreeLayoutOptions): CardScene {
  const direction = o.direction ?? "right";
  const pos = placeTree(tree, o.size, direction, o.wrap);
  const cards: PlacedCard[] = [];
  const byId = new Map<string, PlacedCard>();
  let width = 0;
  let height = 0;
  for (const id of tree.nodes.keys()) {
    const p = pos.get(id);
    if (!p) continue;
    const card: PlacedCard = { ...o.card(id), x: p.x, y: p.y, w: o.size.w, h: o.size.h };
    cards.push(card);
    byId.set(id, card);
    width = Math.max(width, p.x + o.size.w);
    height = Math.max(height, p.y + o.size.h);
  }
  const edges: RoutedEdge[] = [];
  for (const e of tree.edges) {
    const s = byId.get(e.source);
    const t = byId.get(e.target);
    if (!s || !t) continue;
    edges.push({ ...o.edgeStyle(e), id: e.id, source: e.source, target: e.target, ...route(s, t, direction === "down"), quiet: !e.tree });
  }
  // Tree edges last: drawn over the faint cross edges.
  edges.sort((a, b) => Number(!a.quiet) - Number(!b.quiet));
  return { density: o.density, cards, edges, frames: [], width, height, direction };
}
