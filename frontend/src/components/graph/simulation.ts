/**
 * Pure force simulation for the graph engine: pairwise repulsion, a spring
 * per edge and damping. Repulsion switches to Barnes-Hut from
 * `BARNES_HUT_THRESHOLD` nodes.
 */
import { barnesHutRepulsion, exactRepulsion } from "./barnesHut";
import type { ForceSettings, GraphEdge, GraphNode, SimEdge, SimNode, Size } from "./types";

/** Node count from which repulsion switches to Barnes-Hut. */
export const BARNES_HUT_THRESHOLD = 400;

export function radiusOf(n: { degree: number }, scale = 1): number {
  // Modest size variation by degree, capped so even a hub node fits.
  return (4 + Math.min(12, Math.sqrt(n.degree) * 2.5)) * scale;
}

export function neighboursOf<N extends GraphNode>(
  idx: number,
  edges: SimEdge[],
  nodes: SimNode<N>[],
): SimNode<N>[] {
  const seen = new Set<number>();
  const out: SimNode<N>[] = [];
  for (const e of edges) {
    const other = e.fromIdx === idx ? e.toIdx : e.toIdx === idx ? e.fromIdx : -1;
    if (other === -1 || seen.has(other)) continue;
    seen.add(other);
    const n = nodes[other];
    if (n) out.push(n);
  }
  return out;
}

/**
 * Turns plain nodes and edges into simulation state. Nodes start on a ring
 * around the centre with jitter so the simulation does not begin from a
 * singular point. Edges to unknown ids are dropped.
 */
export function buildSimulation<N extends GraphNode>(
  nodes: N[],
  edges: GraphEdge[],
  size: Size,
  random: () => number = Math.random,
): { nodes: SimNode<N>[]; edges: SimEdge[] } {
  const { w, h } = size;
  const idx = new Map<string, number>();
  for (const [i, n] of nodes.entries()) idx.set(n.id, i);
  const simEdges: SimEdge[] = [];
  const counted: number[] = Array.from({ length: nodes.length }, () => 0);
  for (const e of edges) {
    const a = idx.get(e.source);
    const b = idx.get(e.target);
    if (a == null || b == null) continue;
    simEdges.push(e.style ? { fromIdx: a, toIdx: b, style: e.style } : { fromIdx: a, toIdx: b });
    counted[a] = (counted[a] ?? 0) + 1;
    counted[b] = (counted[b] ?? 0) + 1;
  }
  const r = Math.min(w, h) * 0.3;
  const simNodes = nodes.map((n, i) => {
    const angle = (i / Math.max(nodes.length, 1)) * Math.PI * 2;
    return {
      ...n,
      x: w / 2 + Math.cos(angle) * r + (random() - 0.5) * 30,
      y: h / 2 + Math.sin(angle) * r + (random() - 0.5) * 30,
      vx: 0,
      vy: 0,
      pinned: false,
      degree: n.degree ?? counted[i] ?? 0,
    };
  });
  return { nodes: simNodes, edges: simEdges };
}

// Repulsion output, kept across ticks; the repulsion functions clear the part they use.
let forceBuf = new Float64Array(0);

/** Advances physics by one tick. Mutates nodes in place. */
export function stepSimulation(
  nodes: SimNode[],
  edges: SimEdge[],
  size: Size,
  settings: ForceSettings,
): void {
  const N = nodes.length;
  if (N === 0) return;
  const { w, h } = size;

  const k_rep = settings.repulsion;
  const k_spring = settings.linkForce;
  const restLen = settings.linkDistance;
  const centerPull = settings.centerForce;
  const damping = 0.86;

  if (forceBuf.length < 2 * N) forceBuf = new Float64Array(2 * N);
  const forces = forceBuf;
  if (N >= BARNES_HUT_THRESHOLD) barnesHutRepulsion(nodes, k_rep, forces);
  else exactRepulsion(nodes, k_rep, forces);
  for (let i = 0; i < N; i++) {
    const a = nodes[i];
    if (!a || a.pinned) continue;
    a.vx = (a.vx + (forces[2 * i] ?? 0) * 0.016) * damping;
    a.vy = (a.vy + (forces[2 * i + 1] ?? 0) * 0.016) * damping;
  }

  for (let i = 0; i < edges.length; i++) {
    const e = edges[i];
    if (!e) continue;
    const a = nodes[e.fromIdx];
    const b = nodes[e.toIdx];
    if (!a || !b) continue;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
    const stretch = dist - restLen;
    const f = k_spring * stretch;
    const ux = dx / dist;
    const uy = dy / dist;
    if (!a.pinned) {
      a.vx += ux * f;
      a.vy += uy * f;
    }
    if (!b.pinned) {
      b.vx -= ux * f;
      b.vy -= uy * f;
    }
  }

  // Light pull toward centre - keeps disconnected components from
  // drifting to infinity.
  for (let i = 0; i < N; i++) {
    const n = nodes[i];
    if (!n || n.pinned) continue;
    n.vx += (w / 2 - n.x) * centerPull;
    n.vy += (h / 2 - n.y) * centerPull;
    n.x += n.vx;
    n.y += n.vy;
  }
}
