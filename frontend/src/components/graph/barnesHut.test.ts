import { describe, expect, it } from "vitest";

import { barnesHutRepulsion, exactRepulsion, type Body } from "./barnesHut";
import { BARNES_HUT_THRESHOLD, buildSimulation, stepSimulation } from "./simulation";
import type { GraphEdge, GraphNode } from "./types";

const K = 1800;

/** Deterministic PRNG (mulberry32) so failures reproduce. */
function rng(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function scatter(n: number, seed: number, span = 1000): Body[] {
  const random = rng(seed);
  return Array.from({ length: n }, () => ({ x: random() * span, y: random() * span }));
}

function forces(fn: (nodes: Body[], out: Float64Array) => void, nodes: Body[]): Float64Array {
  const out = new Float64Array(2 * nodes.length);
  fn(nodes, out);
  return out;
}

const exact = (nodes: Body[]) => forces((n, out) => exactRepulsion(n, K, out), nodes);
const approx = (nodes: Body[], theta: number) =>
  forces((n, out) => barnesHutRepulsion(n, K, out, theta), nodes);

describe("barnesHutRepulsion", () => {
  it("with theta = 0 equals the exact O(n^2) sum", () => {
    const nodes = scatter(300, 1);
    // Coincident and near-coincident points exercise leaf chains and the depth cap.
    nodes.push({ x: 500, y: 500 }, { x: 500, y: 500 }, { x: 500, y: 500.00001 });
    const want = exact(nodes);
    const got = approx(nodes, 0);
    for (let i = 0; i < want.length; i++) {
      const w = want[i] ?? 0;
      expect(Math.abs((got[i] ?? 0) - w), `component ${i}`).toBeLessThanOrEqual(
        1e-9 * Math.max(1, Math.abs(w)),
      );
    }
  });

  it("with the default theta stays close to the exact forces", () => {
    const nodes = scatter(1000, 2);
    const want = exact(nodes);
    const got = approx(nodes, 0.8);
    let err = 0;
    let norm = 0;
    for (let i = 0; i < want.length; i++) {
      const w = want[i] ?? 0;
      err += ((got[i] ?? 0) - w) ** 2;
      norm += w * w;
    }
    expect(Math.sqrt(err / norm)).toBeLessThan(0.05);
  });

  it("handles no nodes and a single node", () => {
    expect(approx([], 0.8)).toEqual(new Float64Array(0));
    expect(Array.from(approx([{ x: 3, y: 4 }], 0.8))).toEqual([0, 0]);
  });

  it("keeps many coincident nodes finite", () => {
    const nodes = Array.from({ length: 50 }, () => ({ x: 10, y: 10 }));
    const got = approx(nodes, 0.8);
    expect(got.every(Number.isFinite)).toBe(true);
    expect(Array.from(got)).toEqual(Array.from(exact(nodes)));
  });
});

describe("stepSimulation above the Barnes-Hut threshold", () => {
  const FORCES = { repulsion: K, linkDistance: 100, linkForce: 0.02, centerForce: 0.002 };
  const size = { w: 1600, h: 1200 };

  function bigGraph(n: number) {
    const random = rng(3);
    const nodes: GraphNode[] = Array.from({ length: n }, (_, i) => ({ id: `n${i}`, label: `n${i}` }));
    const edges: GraphEdge[] = Array.from({ length: n }, (_, i) => ({
      source: `n${i}`,
      target: `n${Math.floor(random() * n)}`,
    }));
    return buildSimulation(nodes, edges, size, random);
  }

  it("steps 2000 nodes within the frame budget", () => {
    expect(2000).toBeGreaterThanOrEqual(BARNES_HUT_THRESHOLD);
    const g = bigGraph(2000);
    stepSimulation(g.nodes, g.edges, size, FORCES); // warm-up: JIT compile
    // Best of several steps: a shared CI runner can stall any single one.
    let best = Infinity;
    for (let run = 0; run < 5; run++) {
      const start = performance.now();
      stepSimulation(g.nodes, g.edges, size, FORCES);
      best = Math.min(best, performance.now() - start);
    }
    expect(best).toBeLessThan(200);
    expect(g.nodes.every((n) => Number.isFinite(n.x) && Number.isFinite(n.y))).toBe(true);
  });
});
