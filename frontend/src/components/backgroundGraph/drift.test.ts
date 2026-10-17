import { describe, expect, it } from "vitest";
import { linkStrength, NODE_COUNT, scaleNodes, seedNodes, stepNodes, type DriftNode } from "./drift";

const node = (over: Partial<DriftNode>): DriftNode => ({ x: 0, y: 0, vx: 0, vy: 0, r: 1, brand: false, ...over });

describe("drift", () => {
  it("scatters nodes within the screen, a few in the brand colour", () => {
    const nodes = seedNodes(400, 300);
    expect(nodes).toHaveLength(NODE_COUNT);
    for (const n of nodes) {
      expect(n.x).toBeGreaterThanOrEqual(0);
      expect(n.x).toBeLessThanOrEqual(400);
      expect(n.y).toBeLessThanOrEqual(300);
    }
    const brand = nodes.filter((n) => n.brand).length;
    expect(brand).toBeGreaterThan(0);
    expect(brand).toBeLessThan(NODE_COUNT / 4);
  });

  it("caps the speed and wraps a node to the opposite edge", () => {
    const fast = node({ x: 100, y: 100, vx: 5, vy: 0 });
    const leaving = node({ x: -11, y: 50 });
    stepNodes([fast, leaving], 200, 200, () => 0.5);
    expect(Math.hypot(fast.vx, fast.vy)).toBeCloseTo(0.35);
    expect(leaving.x).toBe(210);
  });

  it("rescales positions together with the window", () => {
    const n = node({ x: 1000, y: 400 });
    scaleNodes([n], 0.25, 2);
    expect([n.x, n.y]).toEqual([250, 800]);
  });

  it("link strength falls to zero with distance", () => {
    const a = node({});
    expect(linkStrength(a, node({}), 10)).toBe(1);
    expect(linkStrength(a, node({ x: 5 }), 10)).toBeCloseTo(0.75);
    expect(linkStrength(a, node({ x: 10 }), 10)).toBe(0);
  });
});
