/**
 * Whole card scene: one layered block per independent graph, each in a
 * titled frame, the unlinked cards in a grid frame of their own, and the
 * frames packed in rows whose width is picked to match the viewport shape.
 * Pure and deterministic.
 */
import { layoutComponent, type Metrics } from "./cardLayout";
import { pushTo } from "./layered";
import {
  FRAME_HEADER,
  FRAME_PAD,
  type CardEdge,
  type CardNode,
  type CardScene,
  type CardSize,
  type Density,
  type Direction,
  type Frame,
  type PlacedCard,
  type RoutedEdge,
} from "./cardTypes";

interface FrameTitle {
  label: string;
  count?: string;
}

export interface SceneOptions {
  size: CardSize;
  /** What a close-up card shows; `normal` when omitted. */
  density?: Density;
  direction?: Direction;
  /** Edge kinds that order cards into layers (target before source). */
  layerKinds: ReadonlySet<string>;
  /** Draw a titled frame around every group; off for a single small graph. */
  frames?: boolean;
  frameTitle?: (members: CardNode[], root: CardNode | undefined) => FrameTitle;
  unlinkedTitle?: (count: number) => FrameTitle;
  /** Width over height of the viewport the scene should fill. */
  aspect?: number;
  /**
   * Layers with more cards than this wrap; unlimited when omitted. Several
   * values are tried and the one that fills the viewport best is kept.
   */
  maxPerRow?: number | readonly number[];
  gapX?: number;
  gapY?: number;
  sweeps?: number;
}

interface Block {
  cards: PlacedCard[];
  routes: RoutedEdge[];
  frame: Frame | null;
  w: number;
  h: number;
}

const BLOCK_GAP = 48;
/** World size a frame title is expected at when the frame is sized for it. */
const TITLE_EM = 15;
const TITLE_MAX_W = 560;

/** Rough width of a frame title, so a narrow group still gets a frame its name fits. */
function titleWidth(title: FrameTitle): number {
  const chars = title.label.length + (title.count ? title.count.length + 3 : 0);
  return Math.min(TITLE_MAX_W, chars * TITLE_EM * 0.56 + 40);
}
const UNLINKED_ROW_GAP = 14;

function placeBlock(
  members: CardNode[],
  positions: Map<string, { x: number; y: number }>,
  size: CardSize,
  width: number,
  height: number,
  title: FrameTitle | null,
  routes: RoutedEdge[],
): Block {
  // A frame is at least as wide as its title; the cards are centred in it.
  const w = title ? Math.max(width + FRAME_PAD * 2, titleWidth(title)) : width;
  const inset = title ? { x: (w - width) / 2, y: FRAME_PAD + FRAME_HEADER } : { x: 0, y: 0 };
  const cards = members.map((n) => {
    const p = positions.get(n.id) ?? { x: 0, y: 0 };
    return { ...n, x: p.x + inset.x, y: p.y + inset.y, w: size.w, h: size.h };
  });
  const moved = routes.map((r) => ({ ...r, points: r.points.map((p) => ({ x: p.x + inset.x, y: p.y + inset.y })) }));
  const h = height + (title ? FRAME_PAD * 2 + FRAME_HEADER : 0);
  return { cards, routes: moved, frame: title ? { x: 0, y: 0, w, h, ...title } : null, w, h };
}

function unlinkedBlock(members: CardNode[], m: Metrics, size: CardSize, title: FrameTitle | null): Block {
  const cols = Math.max(1, Math.min(members.length, Math.round(Math.sqrt(members.length * 2))));
  const positions = new Map<string, { x: number; y: number }>();
  const sorted = [...members].sort((a, b) => a.title.localeCompare(b.title) || (a.id < b.id ? -1 : 1));
  for (const [i, n] of sorted.entries()) {
    positions.set(n.id, {
      x: (i % cols) * (size.w + m.gapX),
      y: Math.floor(i / cols) * (size.h + UNLINKED_ROW_GAP),
    });
  }
  const rows = Math.ceil(members.length / cols);
  const width = cols * size.w + (cols - 1) * m.gapX;
  const height = rows * size.h + (rows - 1) * UNLINKED_ROW_GAP;
  return placeBlock(sorted, positions, size, width, height, title, []);
}

/** Shelf packing at one row width; returns the offset of every block. */
function shelf(blocks: Block[], limit: number): { offsets: Array<{ x: number; y: number }>; w: number; h: number } {
  const offsets: Array<{ x: number; y: number }> = [];
  let x = 0;
  let y = 0;
  let rowH = 0;
  let w = 0;
  for (const b of blocks) {
    if (x > 0 && x + b.w > limit) {
      x = 0;
      y += rowH + BLOCK_GAP;
      rowH = 0;
    }
    offsets.push({ x, y });
    w = Math.max(w, x + b.w);
    x += b.w + BLOCK_GAP;
    rowH = Math.max(rowH, b.h);
  }
  return { offsets, w, h: y + rowH };
}

/** Zoom a box of `w` x `h` gets when fitted to a viewport of this shape (height 1). */
function fitScore(w: number, h: number, aspect: number): number {
  return Math.min(aspect / Math.max(1, w), 1 / Math.max(1, h));
}

/**
 * Places each block at the free corner (right of or below a placed block)
 * that keeps the fitted zoom largest, so small groups fill the space beside
 * a big one instead of starting a new row under it.
 */
function corners(blocks: Block[], aspect: number): ReturnType<typeof shelf> {
  const placed: Array<{ x: number; y: number; w: number; h: number }> = [];
  let w = 0;
  let h = 0;
  for (const b of blocks) {
    const spots = [{ x: 0, y: 0 }];
    for (const p of placed) spots.push({ x: p.x + p.w + BLOCK_GAP, y: p.y }, { x: p.x, y: p.y + p.h + BLOCK_GAP });
    let best = { x: 0, y: h + (placed.length ? BLOCK_GAP : 0), score: -1 };
    for (const s of spots) {
      const clash = placed.some(
        (p) => s.x < p.x + p.w + BLOCK_GAP && p.x < s.x + b.w + BLOCK_GAP && s.y < p.y + p.h + BLOCK_GAP && p.y < s.y + b.h + BLOCK_GAP,
      );
      if (clash) continue;
      const score = fitScore(Math.max(w, s.x + b.w), Math.max(h, s.y + b.h), aspect);
      if (score > best.score + 1e-12 || (Math.abs(score - best.score) <= 1e-12 && s.y + s.x < best.y + best.x)) {
        best = { ...s, score };
      }
    }
    placed.push({ x: best.x, y: best.y, w: b.w, h: b.h });
    w = Math.max(w, best.x + b.w);
    h = Math.max(h, best.y + b.h);
  }
  return { offsets: placed.map((p) => ({ x: p.x, y: p.y })), w, h };
}

/** The packing, shelves of several widths or corners, that gets the largest zoom when fitted. */
function pack(blocks: Block[], aspect: number): ReturnType<typeof shelf> & { score: number } {
  const widest = blocks.reduce((mx, b) => Math.max(mx, b.w), 0);
  const total = blocks.reduce((sum, b) => sum + b.w + BLOCK_GAP, 0);
  const packed = corners(blocks, aspect);
  let best = { ...packed, score: fitScore(packed.w, packed.h, aspect) };
  for (let limit = widest; limit <= total * 1.15 && limit > 0; limit *= 1.12) {
    const result = shelf(blocks, limit);
    const score = fitScore(result.w, result.h, aspect);
    if (score > best.score + 1e-9) best = { ...result, score };
  }
  return best;
}

export function layoutCardScene(nodes: CardNode[], edges: CardEdge[], o: SceneOptions): CardScene {
  const direction = o.direction ?? "down";
  const density = o.density ?? "normal";
  const framed = o.frames ?? true;
  const m: Metrics = {
    cardW: o.size.w,
    cardH: o.size.h,
    gapX: o.gapX ?? (direction === "down" ? 24 : 84),
    gapY: o.gapY ?? (direction === "down" ? 52 : 18),
  };
  const groups = new Map<number, CardNode[]>();
  const unlinked: CardNode[] = [];
  for (const n of nodes) {
    if (n.component < 0) unlinked.push(n);
    else pushTo(groups, n.component, n);
  }
  const layoutAll = (maxPerRow: number) => {
    const blocks: Block[] = [];
    for (const c of [...groups.keys()].sort((a, b) => a - b)) {
      const members = groups.get(c) ?? [];
      const ids = new Set(members.map((n) => n.id));
      const own = edges.filter((e) => ids.has(e.source) && ids.has(e.target));
      const layout = layoutComponent(members, own, m, {
        direction,
        layerKinds: o.layerKinds,
        maxPerRow,
        sweeps: o.sweeps ?? 12,
      });
      const root = members.find((n) => n.id === layout.rootId);
      const title = framed ? (o.frameTitle?.(members, root) ?? { label: root?.title ?? "" }) : null;
      blocks.push(placeBlock(members, layout.positions, o.size, layout.width, layout.height, title, layout.routes));
    }
    if (unlinked.length > 0) {
      const title = framed ? (o.unlinkedTitle?.(unlinked.length) ?? { label: "" }) : null;
      blocks.push(unlinkedBlock(unlinked, m, o.size, title));
    }
    return { blocks, packed: pack(blocks, aspect) };
  };
  if (nodes.length === 0) return { density, cards: [], edges: [], frames: [], width: 0, height: 0, direction };

  const aspect = o.aspect ?? 16 / 9;
  const limits = typeof o.maxPerRow === "number" ? [o.maxPerRow] : (o.maxPerRow ?? [Infinity]);
  let best: ReturnType<typeof layoutAll> | null = null;
  for (const limit of limits) {
    const run = layoutAll(limit);
    if (!best || run.packed.score > best.packed.score + 1e-9) best = run;
  }
  if (!best) return { density, cards: [], edges: [], frames: [], width: 0, height: 0, direction };
  const { blocks, packed } = best;
  const cards: PlacedCard[] = [];
  const routed: RoutedEdge[] = [];
  const frames: Frame[] = [];
  for (const [i, b] of blocks.entries()) {
    const off = packed.offsets[i] ?? { x: 0, y: 0 };
    for (const c of b.cards) cards.push({ ...c, x: c.x + off.x, y: c.y + off.y });
    for (const r of b.routes) routed.push({ ...r, points: r.points.map((p) => ({ x: p.x + off.x, y: p.y + off.y })) });
    if (b.frame) frames.push({ ...b.frame, x: off.x, y: off.y });
  }
  return { density, cards, edges: routed, frames, width: packed.w, height: packed.h, direction };
}
