/**
 * Layered card layout of one independent graph, pure and deterministic.
 * Layer-kind edges point from the dependent card to its origin, so origins
 * sit on an earlier layer. Edges spanning several layers get placeholder
 * slots in between, so they run through gaps instead of across cards.
 */
import type { Point } from "./interactions";
import { initialOrder, pullTogether, transpose } from "./cardOrder";
import { assignLayers, breakCycles, byId, minimiseCrossings, pushTo, type Pair } from "./layered";
import { pairKey, type CardEdge, type CardNode, type Direction, type RoutedEdge } from "./cardTypes";

export interface Metrics {
  cardW: number;
  cardH: number;
  /** Space between cards in a row (direction down) or between layers (right). */
  gapX: number;
  /** Space between layers (down) or between cards in a column (right). */
  gapY: number;
}

export interface ComponentLayout {
  /** Top-left corner of every card, relative to the block. */
  positions: Map<string, Point>;
  routes: RoutedEdge[];
  width: number;
  height: number;
  /** First card of the first layer with the most edges: names the group. */
  rootId: string | undefined;
}

export interface ComponentOptions {
  direction: Direction;
  layerKinds: ReadonlySet<string>;
  /** Layers with more real cards than this wrap into several rows. */
  maxPerRow: number;
  sweeps: number;
}

const DUMMY = "\u0000d";
const DUMMY_SIZE = 10;
const DUMMY_GAP = 10;
const ALIGN_PASSES = 8;

const isDummy = (id: string): boolean => id.startsWith(DUMMY);

/** Layer of every card, see steps 1 and 2 of the module comment. */
function layerCards(ids: string[], edges: CardEdge[], kinds: ReadonlySet<string>): Map<string, number> {
  const seen = new Set<string>();
  const directed: Pair[] = [];
  const neighbours = new Map<string, string[]>();
  for (const e of edges) {
    pushTo(neighbours, e.source, e.target);
    pushTo(neighbours, e.target, e.source);
    if (!kinds.has(e.kind)) continue;
    const key = `${e.source}\u0000${e.target}`;
    if (seen.has(key)) continue;
    seen.add(key);
    directed.push([e.source, e.target]);
  }
  const dag = breakCycles(ids, directed);
  const layer = assignLayers(ids, dag);
  const inDag = new Set<string>();
  const hasOrigin = new Set<string>();
  const dependents = new Map<string, string[]>();
  for (const [s, t] of dag) {
    inDag.add(s);
    inDag.add(t);
    hasOrigin.add(s);
    pushTo(dependents, t, s);
  }
  // Origins without origins of their own sit right above their nearest dependent.
  for (const id of ids) {
    if (!inDag.has(id) || hasOrigin.has(id)) continue;
    let nearest = Infinity;
    for (const d of dependents.get(id) ?? []) nearest = Math.min(nearest, layer.get(d) ?? 0);
    if (Number.isFinite(nearest)) layer.set(id, Math.max(0, nearest - 1));
  }
  // Cards joined only by other kinds sit one layer below a neighbour, so the
  // link is a short vertical hop instead of a detour along a crowded row.
  // Breadth first from the ordered cards, nearest layer first, so a chain of
  // such links follows its anchor however long it is.
  const queue = ids.filter((id) => inDag.has(id)).sort((a, b) => (layer.get(a) ?? 0) - (layer.get(b) ?? 0));
  const placed = new Set(queue);
  for (let i = 0; i < queue.length; i++) {
    const id = queue[i];
    if (id === undefined) continue;
    for (const nb of neighbours.get(id) ?? []) {
      if (placed.has(nb)) continue;
      placed.add(nb);
      layer.set(nb, (layer.get(id) ?? 0) + 1);
      queue.push(nb);
    }
  }
  let min = Infinity;
  for (const id of ids) min = Math.min(min, layer.get(id) ?? 0);
  for (const id of ids) layer.set(id, (layer.get(id) ?? 0) - (Number.isFinite(min) ? min : 0));
  return layer;
}

/** Positions across the row: pulled toward `desired`, order and spacing kept. */
function spread(desired: number[], seps: number[]): number[] {
  const n = desired.length;
  const left = desired.slice();
  const right = desired.slice();
  for (let i = 1; i < n; i++) left[i] = Math.max(desired[i] ?? 0, (left[i - 1] ?? 0) + (seps[i - 1] ?? 0));
  for (let i = n - 2; i >= 0; i--) right[i] = Math.min(desired[i] ?? 0, (right[i + 1] ?? 0) - (seps[i] ?? 0));
  // Both passes keep every spacing, so their mean keeps it too.
  return left.map((l, i) => (l + (right[i] ?? l)) / 2);
}

export function layoutComponent(
  members: CardNode[],
  edges: CardEdge[],
  m: Metrics,
  o: ComponentOptions,
): ComponentLayout {
  const ids = members.map((n) => n.id).sort(byId);
  const idSet = new Set(ids);
  const inner = edges.filter((e) => e.source !== e.target && idSet.has(e.source) && idSet.has(e.target));
  const layer = layerCards(ids, inner, o.layerKinds);
  const layerOf = (id: string) => layer.get(id) ?? 0;
  const count = ids.reduce((mx, id) => Math.max(mx, layerOf(id) + 1), 0);

  const layers: string[][] = Array.from({ length: count }, () => []);
  for (const id of ids) layers[layerOf(id)]?.push(id);
  const chains = new Map<string, string[]>();
  const segments: Array<{ source: string; target: string }> = [];
  let dummies = 0;
  const owner = new Map<string, string>();
  for (const e of inner) {
    const la = layerOf(e.source);
    const lb = layerOf(e.target);
    if (la === lb) continue;
    const [upper, lower] = la < lb ? [e.source, e.target] : [e.target, e.source];
    const chain = [upper];
    for (let l = Math.min(la, lb) + 1; l < Math.max(la, lb); l++) {
      const d = `${DUMMY}${dummies++}`;
      layers[l]?.push(d);
      owner.set(d, upper);
      chain.push(d);
    }
    chain.push(lower);
    for (let i = 1; i < chain.length; i++) segments.push({ source: chain[i - 1] ?? "", target: chain[i] ?? "" });
    chains.set(e.id, chain);
  }
  const links = inner.map((e) => [e.source, e.target] as const);
  const start = initialOrder(layers, links, layerOf, (id) => owner.get(id));
  const sameLayer = links.filter(([a, b]) => layerOf(a) === layerOf(b));
  const swept = transpose(minimiseCrossings(start, segments, o.sweeps), segments);
  const ordered = pullTogether(swept, sameLayer, segments);

  // Rows: a layer, or a slice of one that has too many cards to stay on one line.
  const rows: string[][] = [];
  const rowLayer: number[] = [];
  const dropped = new Set<string>();
  for (const [l, col] of ordered.entries()) {
    const real = col.filter((id) => !isDummy(id));
    if (real.length > o.maxPerRow) {
      for (const id of col) if (isDummy(id)) dropped.add(id);
      for (let i = 0; i < real.length; i += o.maxPerRow) {
        rows.push(real.slice(i, i + o.maxPerRow));
        rowLayer.push(l);
      }
    } else {
      rows.push(col);
      rowLayer.push(l);
    }
  }
  for (const [key, chain] of chains) chains.set(key, chain.filter((id) => !dropped.has(id)));

  const down = o.direction === "down";
  const across = down ? m.cardW : m.cardH;
  const along = down ? m.cardH : m.cardW;
  const gapAcross = down ? m.gapX : m.gapY;
  const gapLayer = down ? m.gapY : m.gapX;
  const sizeOf = (id: string) => (isDummy(id) ? DUMMY_SIZE : across);
  const sep = (a: string, b: string) =>
    (sizeOf(a) + sizeOf(b)) / 2 + (isDummy(a) || isDummy(b) ? DUMMY_GAP : gapAcross);

  const neighbours = new Map<string, string[]>();
  for (const chain of chains.values()) {
    for (let i = 1; i < chain.length; i++) {
      const a = chain[i - 1];
      const b = chain[i];
      if (a === undefined || b === undefined) continue;
      pushTo(neighbours, a, b);
      pushTo(neighbours, b, a);
    }
  }
  const centre = new Map<string, number>();
  const rowSeps = rows.map((row) => row.slice(1).map((id, i) => sep(row[i] ?? id, id)));
  for (const [r, row] of rows.entries()) {
    const seps = rowSeps[r] ?? [];
    const total = seps.reduce((a, b) => a + b, 0);
    let c = -total / 2;
    for (const [i, id] of row.entries()) {
      if (i > 0) c += seps[i - 1] ?? 0;
      centre.set(id, c);
    }
  }
  for (let pass = 0; pass < ALIGN_PASSES; pass++) {
    const order = pass % 2 === 0 ? rows.keys() : [...rows.keys()].reverse();
    for (const r of order) {
      const row = rows[r] ?? [];
      const desired = row.map((id) => {
        const list = neighbours.get(id);
        if (!list || list.length === 0) return centre.get(id) ?? 0;
        // The median ignores one far neighbour that would drag a card across the row.
        const xs = list.map((nb) => centre.get(nb) ?? 0).sort((a, b) => a - b);
        const mid = xs.length >> 1;
        return xs.length % 2 ? (xs[mid] ?? 0) : ((xs[mid - 1] ?? 0) + (xs[mid] ?? 0)) / 2;
      });
      const placed = spread(desired, rowSeps[r] ?? []);
      for (const [i, id] of row.entries()) centre.set(id, placed[i] ?? 0);
    }
  }

  // The rows of a wrapped layer form a grid under its first row, so the gaps
  // between columns stay clear for the routes into the lower rows.
  for (const r of rows.keys()) {
    if (r === 0 || rowLayer[r] !== rowLayer[r - 1]) continue;
    let head = r;
    while (head > 0 && rowLayer[head - 1] === rowLayer[r]) head -= 1;
    const first = rows[head] ?? [];
    for (const [i, id] of (rows[r] ?? []).entries()) centre.set(id, centre.get(first[i] ?? id) ?? 0);
  }

  // Along the layer axis: rows of one layer sit closer than separate layers.
  const rowStart: number[] = [];
  const gapAfter: number[] = [];
  let cursor = 0;
  for (const r of rows.keys()) {
    rowStart.push(cursor);
    const sameLayer = rowLayer[r + 1] === rowLayer[r];
    const gap = sameLayer ? Math.round(gapAcross * 0.6) : gapLayer;
    gapAfter.push(gap);
    cursor += along + gap;
  }
  const rowOf = new Map<string, number>();
  const indexOf = new Map<string, number>();
  for (const [r, row] of rows.entries()) {
    for (const [i, id] of row.entries()) {
      rowOf.set(id, r);
      indexOf.set(id, i);
    }
  }

  let minAcross = Infinity;
  let maxAcross = -Infinity;
  for (const [id, c] of centre) {
    if (dropped.has(id)) continue;
    minAcross = Math.min(minAcross, c - sizeOf(id) / 2);
    maxAcross = Math.max(maxAcross, c + sizeOf(id) / 2);
  }
  if (!Number.isFinite(minAcross)) minAcross = maxAcross = 0;
  const acrossOf = (id: string) => (centre.get(id) ?? 0) - minAcross;
  const alongOf = (id: string) => rowStart[rowOf.get(id) ?? 0] ?? 0;

  const positions = new Map<string, Point>();
  for (const id of ids) {
    const c = acrossOf(id);
    const a = alongOf(id);
    positions.set(id, down ? { x: c - m.cardW / 2, y: a } : { x: a, y: c - m.cardH / 2 });
  }
  const acrossSpan = maxAcross - minAcross;
  const alongSpan = Math.max(0, cursor - (gapAfter[gapAfter.length - 1] ?? 0));
  const pt = (a: number, c: number): Point => (down ? { x: c, y: a } : { x: a, y: c });

  /** Exit (`end` false) or entry point of a card on the layer axis. */
  const port = (id: string, entry: boolean): Point =>
    pt(alongOf(id) + (entry ? 0 : along), acrossOf(id));

  // First and last row of every layer, and the middle of the gap below a layer.
  const firstRow = new Map<number, number>();
  const lastRow = new Map<number, number>();
  for (const [r, l] of rowLayer.entries()) {
    if (!firstRow.has(l)) firstRow.set(l, r);
    lastRow.set(l, r);
  }
  const bandBelow = (id: string): number => {
    const r = lastRow.get(layerOf(id)) ?? 0;
    return (rowStart[r] ?? 0) + along + (gapAfter[r] ?? gapLayer) / 2;
  };
  const middle = (id: string) => alongOf(id) + along / 2;
  /** Across position of the gap before a card, where a channel runs. */
  const channel = (id: string) => acrossOf(id) - across / 2 - gapAcross / 2;

  /**
   * Orthogonal route through the gaps of wrapped layers: out of the card's
   * side when it is not on its layer's last row, along the gap below the
   * layer, and into the target's side when it is not on its layer's first row.
   */
  const channelRoute = (upper: string, lower: string): Point[] => {
    const band = bandBelow(upper);
    const pts: Point[] = [];
    if (rowOf.get(upper) === lastRow.get(layerOf(upper))) {
      pts.push(port(upper, false), pt(band, acrossOf(upper)));
    } else {
      const side = acrossOf(upper) - across / 2;
      pts.push(pt(middle(upper), side), pt(middle(upper), channel(upper)), pt(band, channel(upper)));
    }
    const firstOfLayer = firstRow.get(layerOf(lower)) ?? 0;
    if (rowOf.get(lower) === firstOfLayer && layerOf(lower) === layerOf(upper) + 1) {
      pts.push(pt(band, acrossOf(lower)), port(lower, true));
    } else if (rowOf.get(lower) === firstOfLayer) {
      // Layers in between: down the channel beside the target, then in from above.
      const above = (rowStart[firstOfLayer] ?? 0) - (gapAfter[firstOfLayer - 1] ?? gapLayer) / 2;
      pts.push(pt(band, channel(lower)), pt(above, channel(lower)), pt(above, acrossOf(lower)), port(lower, true));
    } else {
      const side = acrossOf(lower) - across / 2;
      pts.push(pt(band, channel(lower)), pt(middle(lower), channel(lower)), pt(middle(lower), side));
    }
    return pts.filter((p, i) => {
      const q = pts[i - 1];
      return !q || Math.abs(p.x - q.x) > 0.5 || Math.abs(p.y - q.y) > 0.5;
    });
  };

  const routes: RoutedEdge[] = [];
  for (const e of inner) {
    const ra = rowOf.get(e.source) ?? 0;
    const rb = rowOf.get(e.target) ?? 0;
    let points: Point[];
    let shape: RoutedEdge["shape"] = "flow";
    if (ra === rb) {
      const ia = indexOf.get(e.source) ?? 0;
      const ib = indexOf.get(e.target) ?? 0;
      const a0 = alongOf(e.source);
      if (Math.abs(ia - ib) === 1) {
        // Neighbours in a row: a straight hop between their facing sides.
        const sa = ia < ib ? 1 : -1;
        const half = across / 2;
        points = [
          pt(a0 + along / 2, acrossOf(e.source) + sa * half),
          pt(a0 + along / 2, acrossOf(e.target) - sa * half),
        ];
        shape = "side";
      } else {
        const detour = a0 + along + Math.min(22, (gapAfter[ra] ?? gapLayer) * 0.45);
        points = [
          port(e.source, false),
          pt(detour, acrossOf(e.source)),
          pt(detour, acrossOf(e.target)),
          port(e.target, false),
        ];
        shape = "loop";
      }
    } else {
      const [upper, lower] = ra < rb ? [e.source, e.target] : [e.target, e.source];
      const wrappedEnd =
        rowOf.get(upper) !== lastRow.get(layerOf(upper)) || rowOf.get(lower) !== firstRow.get(layerOf(lower));
      const chain = chains.get(e.id) ?? [upper, lower];
      // A long edge whose placeholders fell in wrapped layers has no slots to pass through.
      const lostSlots = chain.length - 2 < layerOf(lower) - layerOf(upper) - 1;
      if (wrappedEnd || lostSlots || layerOf(upper) === layerOf(lower)) {
        points = channelRoute(upper, lower);
        shape = "loop";
      } else {
        points = [port(upper, false)];
        for (const d of chain.slice(1, -1)) points.push(pt(alongOf(d) + along / 2, acrossOf(d)));
        points.push(port(lower, true));
      }
      if (upper !== e.source) points.reverse();
    }
    routes.push({ ...e, points, shape });
  }

  // Parallel edges between the same two cards run side by side, not on top of each other.
  const parallel = new Map<string, RoutedEdge[]>();
  for (const r of routes) pushTo(parallel, pairKey(r.source, r.target), r);
  for (const list of parallel.values()) {
    if (list.length < 2) continue;
    for (const [k, r] of list.entries()) {
      const shift = (k - (list.length - 1) / 2) * 5;
      r.points = r.points.map((p) => (down ? { x: p.x + shift, y: p.y } : { x: p.x, y: p.y + shift }));
    }
  }

  let rootId: string | undefined;
  let rootDegree = -1;
  const degree = new Map<string, number>();
  for (const e of inner) {
    degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
    degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
  }
  for (const id of rows[0] ?? []) {
    if (isDummy(id)) continue;
    const d = degree.get(id) ?? 0;
    if (d > rootDegree) {
      rootDegree = d;
      rootId = id;
    }
  }

  return {
    positions,
    routes,
    width: down ? acrossSpan : alongSpan,
    height: down ? alongSpan : acrossSpan,
    rootId,
  };
}
