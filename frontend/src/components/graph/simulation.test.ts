import { describe, expect, it } from "vitest";

import { buildSimulation, neighboursOf, radiusOf, stepSimulation } from "./simulation";
import type { ForceSettings, GraphNode, SimNode } from "./types";

const FORCES: ForceSettings = {
  repulsion: 1800,
  linkDistance: 100,
  linkForce: 0.02,
  centerForce: 0.002,
};

function node(id: string, x: number, y: number, extra: Partial<SimNode> = {}): SimNode {
  return { id, label: id, x, y, vx: 0, vy: 0, pinned: false, degree: 0, ...extra };
}

describe("radiusOf", () => {
  it("grows with degree and caps for hubs", () => {
    expect(radiusOf({ degree: 0 })).toBe(4);
    expect(radiusOf({ degree: 4 })).toBeGreaterThan(radiusOf({ degree: 1 }));
    expect(radiusOf({ degree: 10_000 })).toBe(16);
    expect(radiusOf({ degree: 0 }, 2)).toBe(8);
  });
});

describe("buildSimulation", () => {
  const nodes: GraphNode[] = [
    { id: "a", label: "A" },
    { id: "b", label: "B" },
    { id: "c", label: "C", degree: 7 },
  ];

  it("indexes edges, drops unknown ids and keeps styles", () => {
    const g = buildSimulation(
      nodes,
      [
        { source: "a", target: "b", style: { dashed: true } },
        { source: "a", target: "zzz" },
      ],
      { w: 800, h: 600 },
      () => 0.5,
    );
    expect(g.edges).toEqual([{ fromIdx: 0, toIdx: 1, style: { dashed: true } }]);
  });

  it("uses explicit degree or counts edges", () => {
    const g = buildSimulation(nodes, [{ source: "a", target: "b" }], { w: 800, h: 600 }, () => 0.5);
    expect(g.nodes.map((n) => n.degree)).toEqual([1, 1, 7]);
  });

  it("places nodes on a ring around the centre", () => {
    const g = buildSimulation(nodes, [], { w: 800, h: 600 }, () => 0.5);
    for (const n of g.nodes) {
      const d = Math.hypot(n.x - 400, n.y - 300);
      expect(d).toBeCloseTo(180, 5);
      expect(n.pinned).toBe(false);
    }
  });
});

describe("neighboursOf", () => {
  it("returns each neighbour once, in either direction", () => {
    const nodes = [node("a", 0, 0), node("b", 1, 0), node("c", 2, 0)];
    const edges = [
      { fromIdx: 0, toIdx: 1 },
      { fromIdx: 1, toIdx: 0 },
      { fromIdx: 2, toIdx: 0 },
    ];
    expect(neighboursOf(0, edges, nodes).map((n) => n.id)).toEqual(["b", "c"]);
  });
});

describe("stepSimulation", () => {
  it("pushes close nodes apart", () => {
    const nodes = [node("a", 390, 300), node("b", 410, 300)];
    stepSimulation(nodes, [], { w: 800, h: 600 }, FORCES);
    const [a, b] = nodes;
    expect(a?.x).toBeLessThan(390);
    expect(b?.x).toBeGreaterThan(410);
  });

  it("pulls a stretched edge together", () => {
    const nodes = [node("a", 0, 300), node("b", 800, 300)];
    const settings = { ...FORCES, repulsion: 0, centerForce: 0 };
    stepSimulation(nodes, [{ fromIdx: 0, toIdx: 1 }], { w: 800, h: 600 }, settings);
    expect(nodes[0]?.x).toBeGreaterThan(0);
    expect(nodes[1]?.x).toBeLessThan(800);
  });

  it("leaves pinned nodes in place", () => {
    const nodes = [node("a", 400, 300, { pinned: true }), node("b", 401, 300)];
    stepSimulation(nodes, [{ fromIdx: 0, toIdx: 1 }], { w: 800, h: 600 }, FORCES);
    expect(nodes[0]).toMatchObject({ x: 400, y: 300, vx: 0, vy: 0 });
  });

  it("separates coincident nodes deterministically", () => {
    const nodes = [node("a", 400, 300), node("b", 400, 300)];
    stepSimulation(nodes, [], { w: 800, h: 600 }, FORCES);
    expect(nodes[0]?.x).not.toBe(nodes[1]?.x);
    expect(Number.isFinite(nodes[0]?.x)).toBe(true);
  });

  it("is a no-op on an empty graph", () => {
    expect(() => stepSimulation([], [], { w: 1, h: 1 }, FORCES)).not.toThrow();
  });
});
