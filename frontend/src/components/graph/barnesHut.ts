/**
 * Coulomb-style repulsion (~k/r^2), exact or Barnes-Hut: a cell of side `s`
 * at distance `d` counts as one body when `s / d < theta` (`theta = 0` is exact).
 * Hot loops use indexed `for` on purpose: iterators cost 5-15% here.
 */

/** Anything with a position; the simulation passes its `SimNode`s. */
export interface Body {
  x: number;
  y: number;
}

/** Default accuracy of the approximation; 0.8 keeps the layout visually unchanged. */
const DEFAULT_THETA = 0.8;

// Deeper cells only chain their bodies; stops endless splitting of near-coincident points.
const MAX_DEPTH = 24;

// Traversal stack: each pop pushes at most 4 cells, one level deeper.
const STACK = new Int32Array(4 * (MAX_DEPTH + 2));

/** Force on `a` (index `i`) from `b` (index `j`), added to `out[0]`, `out[1]`. */
function pairForce(
  a: Body,
  b: Body,
  i: number,
  j: number,
  k: number,
  out: Float64Array,
  o: number,
): void {
  let dx = a.x - b.x;
  let dy = a.y - b.y;
  let dist2 = dx * dx + dy * dy;
  if (dist2 < 0.01) {
    // Coincident nodes: push apart deterministically, equal and opposite.
    dx = (i - j) * 0.5;
    dy = i < j ? 0.5 : -0.5;
    dist2 = 1;
  }
  const f = k / dist2;
  const dist = Math.sqrt(dist2);
  out[o] = (out[o] ?? 0) + (dx / dist) * f;
  out[o + 1] = (out[o + 1] ?? 0) + (dy / dist) * f;
}

/**
 * Exact O(n^2) repulsion. Writes the force on node `i` to `out[2i]`,
 * `out[2i + 1]`; `out` must hold `2 * nodes.length` values. Each pair is
 * visited once and applies equal and opposite forces to both ends.
 */
export function exactRepulsion(nodes: readonly Body[], k: number, out: Float64Array): void {
  const n = nodes.length;
  out.fill(0, 0, 2 * n);
  for (let i = 0; i < n; i++) {
    const a = nodes[i];
    if (!a) continue;
    const oi = 2 * i;
    for (let j = i + 1; j < n; j++) {
      const b = nodes[j];
      if (!b) continue;
      let dx = a.x - b.x;
      let dy = a.y - b.y;
      let dist2 = dx * dx + dy * dy;
      if (dist2 < 0.01) {
        // Same rule as `pairForce` for i < j.
        dx = (i - j) * 0.5;
        dy = 0.5;
        dist2 = 1;
      }
      const f = k / dist2;
      const dist = Math.sqrt(dist2);
      const fx = (dx / dist) * f;
      const fy = (dy / dist) * f;
      const oj = 2 * j;
      out[oi] = (out[oi] ?? 0) + fx;
      out[oi + 1] = (out[oi + 1] ?? 0) + fy;
      out[oj] = (out[oj] ?? 0) - fx;
      out[oj + 1] = (out[oj + 1] ?? 0) - fy;
    }
  }
}

/** Flat-array quadtree; cell 0 is the root. Arrays grow by doubling. */
interface QuadTree {
  count: number;
  x0: Float64Array;
  y0: Float64Array;
  size: Float64Array;
  mass: Float64Array;
  sx: Float64Array;
  sy: Float64Array;
  /** Leaf: first body of its chain, -1 when empty. */
  first: Int32Array;
  /** Internal: 4 child cells per cell, -1 when absent. */
  children: Int32Array;
  internal: Uint8Array;
  /** Next body in the same leaf chain, -1 at the end. */
  next: Int32Array;
}

function allocTree(capacity: number, bodies: number): QuadTree {
  return {
    count: 0,
    x0: new Float64Array(capacity),
    y0: new Float64Array(capacity),
    size: new Float64Array(capacity),
    mass: new Float64Array(capacity),
    sx: new Float64Array(capacity),
    sy: new Float64Array(capacity),
    first: new Int32Array(capacity).fill(-1),
    children: new Int32Array(capacity * 4).fill(-1),
    internal: new Uint8Array(capacity),
    next: new Int32Array(bodies).fill(-1),
  };
}

function ensureCapacity(t: QuadTree, needed: number): QuadTree {
  if (needed <= t.x0.length) return t;
  const grown = allocTree(Math.max(needed, t.x0.length * 2), 0);
  grown.count = t.count;
  grown.x0.set(t.x0);
  grown.y0.set(t.y0);
  grown.size.set(t.size);
  grown.mass.set(t.mass);
  grown.sx.set(t.sx);
  grown.sy.set(t.sy);
  grown.first.set(t.first);
  grown.children.set(t.children);
  grown.internal.set(t.internal);
  grown.next = t.next;
  return grown;
}

// The tree is rebuilt every tick; its buffers are kept and cleared instead of reallocated.
let cached: QuadTree | null = null;

/** The cached tree cleared for a new build, or a fresh one when it is too small. */
function resetTree(capacity: number, bodies: number): QuadTree {
  const t = cached;
  if (!t || t.x0.length < capacity || t.next.length < bodies) return allocTree(capacity, bodies);
  const used = t.count;
  t.count = 0;
  t.mass.fill(0, 0, used);
  t.sx.fill(0, 0, used);
  t.sy.fill(0, 0, used);
  t.first.fill(-1, 0, used);
  t.children.fill(-1, 0, 4 * used);
  t.internal.fill(0, 0, used);
  t.next.fill(-1, 0, bodies);
  return t;
}

function newCell(t: QuadTree, x0: number, y0: number, size: number): number {
  const c = t.count++;
  t.x0[c] = x0;
  t.y0[c] = y0;
  t.size[c] = size;
  return c;
}

function quadrant(t: QuadTree, c: number, x: number, y: number): number {
  const half = (t.size[c] ?? 0) / 2;
  return (x >= (t.x0[c] ?? 0) + half ? 1 : 0) | (y >= (t.y0[c] ?? 0) + half ? 2 : 0);
}

function childCell(t: QuadTree, c: number, q: number): number {
  const half = (t.size[c] ?? 0) / 2;
  const child = newCell(t, (t.x0[c] ?? 0) + (q & 1) * half, (t.y0[c] ?? 0) + (q >> 1) * half, half);
  t.children[4 * c + q] = child;
  return child;
}

function addMass(t: QuadTree, c: number, m: number, sx: number, sy: number): void {
  t.mass[c] = (t.mass[c] ?? 0) + m;
  t.sx[c] = (t.sx[c] ?? 0) + sx;
  t.sy[c] = (t.sy[c] ?? 0) + sy;
}

function insert(t: QuadTree, nodes: readonly Body[], b: number, x: number, y: number): void {
  let c = 0;
  for (let depth = 0; ; depth++) {
    if (!t.internal[c]) {
      const head = t.first[c] ?? -1;
      if (head === -1) {
        t.first[c] = b;
        addMass(t, c, 1, x, y);
        return;
      }
      const h = nodes[head];
      if (!h || depth >= MAX_DEPTH || (h.x === x && h.y === y)) {
        t.next[b] = head;
        t.first[c] = b;
        addMass(t, c, 1, x, y);
        return;
      }
      // Split: the existing chain (all at one point) moves to a child.
      const moved = childCell(t, c, quadrant(t, c, h.x, h.y));
      t.first[moved] = head;
      addMass(t, moved, t.mass[c] ?? 0, t.sx[c] ?? 0, t.sy[c] ?? 0);
      t.first[c] = -1;
      t.internal[c] = 1;
    }
    addMass(t, c, 1, x, y);
    const q = quadrant(t, c, x, y);
    const child = t.children[4 * c + q] ?? -1;
    if (child === -1) {
      const leaf = childCell(t, c, q);
      t.first[leaf] = b;
      addMass(t, leaf, 1, x, y);
      return;
    }
    c = child;
  }
}

function buildTree(nodes: readonly Body[]): QuadTree {
  const n = nodes.length;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (let i = 0; i < n; i++) {
    const a = nodes[i];
    if (!a) continue;
    if (a.x < minX) minX = a.x;
    if (a.y < minY) minY = a.y;
    if (a.x > maxX) maxX = a.x;
    if (a.y > maxY) maxY = a.y;
  }
  let t = resetTree(4 * n + MAX_DEPTH + 2, n);
  // Slightly larger than the bounding box so the extreme points fall inside.
  const side = (Math.max(maxX - minX, maxY - minY) || 1) * 1.001;
  newCell(t, minX, minY, side);
  for (let i = 0; i < n; i++) {
    const a = nodes[i];
    if (!a) continue;
    t = ensureCapacity(t, t.count + MAX_DEPTH + 2);
    insert(t, nodes, i, a.x, a.y);
  }
  cached = t;
  return t;
}

/**
 * Barnes-Hut repulsion, same output contract as `exactRepulsion`. A cell
 * containing the node itself is always opened, so a node never pushes on
 * itself through a centre of mass.
 */
export function barnesHutRepulsion(
  nodes: readonly Body[],
  k: number,
  out: Float64Array,
  theta: number = DEFAULT_THETA,
): void {
  const n = nodes.length;
  out.fill(0, 0, 2 * n);
  if (n === 0) return;
  const t = buildTree(nodes);
  const theta2 = theta * theta;
  const stack = STACK;
  for (let i = 0; i < n; i++) {
    const a = nodes[i];
    if (!a) continue;
    const o = 2 * i;
    let sp = 0;
    stack[sp++] = 0;
    while (sp > 0) {
      const c = stack[--sp] ?? 0;
      const m = t.mass[c] ?? 0;
      if (m === 0) continue;
      if (!t.internal[c]) {
        for (let j = t.first[c] ?? -1; j !== -1; j = t.next[j] ?? -1) {
          if (j === i) continue;
          const b = nodes[j];
          if (b) pairForce(a, b, i, j, k, out, o);
        }
        continue;
      }
      const s = t.size[c] ?? 0;
      const x0 = t.x0[c] ?? 0;
      const y0 = t.y0[c] ?? 0;
      const inside = a.x >= x0 && a.x < x0 + s && a.y >= y0 && a.y < y0 + s;
      const dx = a.x - (t.sx[c] ?? 0) / m;
      const dy = a.y - (t.sy[c] ?? 0) / m;
      const dist2 = dx * dx + dy * dy;
      if (!inside && s * s < theta2 * dist2) {
        const f = (k * m) / dist2;
        const dist = Math.sqrt(dist2);
        out[o] = (out[o] ?? 0) + (dx / dist) * f;
        out[o + 1] = (out[o + 1] ?? 0) + (dy / dist) * f;
        continue;
      }
      for (let q = 0; q < 4; q++) {
        const child = t.children[4 * c + q] ?? -1;
        if (child !== -1) stack[sp++] = child;
      }
    }
  }
}
