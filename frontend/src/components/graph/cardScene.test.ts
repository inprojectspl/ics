import { describe, expect, it } from "vitest";

import { layoutCardScene, type SceneOptions } from "./cardScene";
import type { CardEdge, CardNode, CardScene, PlacedCard } from "./cardTypes";

const card = (id: string, component = 0, title = id.toUpperCase()): CardNode => ({
  id,
  title,
  color: "#000",
  component,
});
const edge = (source: string, target: string, kind = "derived_from"): CardEdge => ({
  id: `${source}>${target}:${kind}`,
  source,
  target,
  kind,
  width: 1,
});

const OPTIONS: SceneOptions = {
  size: { w: 200, h: 60 },
  layerKinds: new Set(["derived_from", "depends_on"]),
  frameTitle: (members, root) => ({ label: root?.title ?? "", count: String(members.length) }),
  unlinkedTitle: (n) => ({ label: "unlinked", count: String(n) }),
};

const byId = (scene: CardScene, id: string): PlacedCard => {
  const found = scene.cards.find((c) => c.id === id);
  if (!found) throw new Error(`no card ${id}`);
  return found;
};

function overlaps(a: { x: number; y: number; w: number; h: number }, b: typeof a): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

/** A project-like graph: a chain with a fan, a second graph and loose cards. */
function sample(): { nodes: CardNode[]; edges: CardEdge[] } {
  const nodes = [
    ...["goal", "req1", "req2", "arch", "spec1", "spec2", "spec3", "run", "note"].map((id) => card(id, 0)),
    ...["ml", "mlreq", "mlarch"].map((id) => card(id, 1)),
    card("loose1", -1),
    card("loose2", -1),
  ];
  const edges = [
    edge("req1", "goal"),
    edge("req2", "goal"),
    edge("arch", "req1"),
    edge("arch", "req2"),
    edge("spec1", "arch"),
    edge("spec2", "arch"),
    edge("spec3", "goal"),
    edge("run", "spec1", "depends_on"),
    edge("note", "goal", "relates_to"),
    edge("spec2", "spec3", "relates_to"),
    edge("mlreq", "ml"),
    edge("mlarch", "mlreq"),
  ];
  return { nodes, edges };
}

describe("layoutCardScene", () => {
  it("never overlaps two cards", () => {
    const { nodes, edges } = sample();
    for (const maxPerRow of [undefined, 2, 1]) {
      const scene = layoutCardScene(nodes, edges, { ...OPTIONS, maxPerRow });
      expect(scene.cards).toHaveLength(nodes.length);
      for (const [i, a] of scene.cards.entries()) {
        for (const b of scene.cards.slice(i + 1)) expect(overlaps(a, b), `${a.id} / ${b.id}`).toBe(false);
      }
    }
  });

  it("puts origins above what is derived from them and flows edges between rows", () => {
    const { nodes, edges } = sample();
    const scene = layoutCardScene(nodes, edges, OPTIONS);
    expect(byId(scene, "goal").y).toBeLessThan(byId(scene, "req1").y);
    expect(byId(scene, "req1").y).toBeLessThan(byId(scene, "arch").y);
    expect(byId(scene, "arch").y).toBeLessThan(byId(scene, "spec1").y);
    expect(byId(scene, "spec1").y).toBeLessThan(byId(scene, "run").y);
    // Joined only by a weak relation: one row under its neighbour.
    expect(byId(scene, "note").y).toBeGreaterThan(byId(scene, "goal").y);
    const route = scene.edges.find((e) => e.source === "req1" && e.target === "goal");
    expect(route?.shape).toBe("flow");
    // The route runs from the source (below) to the target (above).
    expect(route?.points[0]?.y).toBeGreaterThan(route?.points.at(-1)?.y ?? Infinity);
  });

  it("lays origins out to the left in the right-hand direction", () => {
    const { nodes, edges } = sample();
    const scene = layoutCardScene(nodes, edges, { ...OPTIONS, direction: "right" });
    expect(byId(scene, "goal").x).toBeLessThan(byId(scene, "req1").x);
    expect(byId(scene, "req1").x).toBeLessThan(byId(scene, "arch").x);
    expect(scene.direction).toBe("right");
  });

  it("gives every graph its own frame with the cards inside and no frame overlapping another", () => {
    const { nodes, edges } = sample();
    const scene = layoutCardScene(nodes, edges, OPTIONS);
    expect(scene.frames.map((f) => f.label)).toEqual(["GOAL", "ML", "unlinked"]);
    expect(scene.frames.map((f) => f.count)).toEqual(["9", "3", "2"]);
    for (const [i, a] of scene.frames.entries()) {
      for (const b of scene.frames.slice(i + 1)) expect(overlaps(a, b)).toBe(false);
    }
    const inside = (id: string, frame: number) => {
      const c = byId(scene, id);
      const f = scene.frames[frame];
      return !!f && c.x >= f.x && c.y >= f.y && c.x + c.w <= f.x + f.w && c.y + c.h <= f.y + f.h;
    };
    expect(inside("arch", 0)).toBe(true);
    expect(inside("mlarch", 1)).toBe(true);
    expect(inside("loose2", 2)).toBe(true);
    for (const c of scene.cards) {
      expect(c.x + c.w).toBeLessThanOrEqual(scene.width + 0.001);
      expect(c.y + c.h).toBeLessThanOrEqual(scene.height + 0.001);
    }
  });

  it("returns the same scene whatever the input order", () => {
    const { nodes, edges } = sample();
    const a = layoutCardScene(nodes, edges, OPTIONS);
    const b = layoutCardScene([...nodes].reverse(), [...edges].reverse(), OPTIONS);
    const pos = (s: CardScene) => new Map(s.cards.map((c) => [c.id, `${c.x.toFixed(3)},${c.y.toFixed(3)}`]));
    expect(pos(b)).toEqual(pos(a));
    expect(b.frames).toEqual(a.frames);
  });

  it("packs groups to follow the viewport shape", () => {
    const nodes = Array.from({ length: 8 }, (_, i) => [card(`a${i}`, i), card(`b${i}`, i)]).flat();
    const edges = Array.from({ length: 8 }, (_, i) => edge(`b${i}`, `a${i}`));
    const wide = layoutCardScene(nodes, edges, { ...OPTIONS, aspect: 4 });
    const tall = layoutCardScene(nodes, edges, { ...OPTIONS, aspect: 0.5 });
    expect(wide.width / wide.height).toBeGreaterThan(tall.width / tall.height);
  });

  it("routes a link between two cards of one row sideways, and a longer one through the gap", () => {
    const nodes = ["o", "a", "b", "c"].map((id) => card(id));
    const edges = [edge("a", "o"), edge("b", "o"), edge("c", "o"), edge("a", "b", "relates_to"), edge("a", "c", "relates_to")];
    const scene = layoutCardScene(nodes, edges, { ...OPTIONS, frames: false });
    const shapes = scene.edges.filter((e) => e.kind === "relates_to").map((e) => e.shape).sort();
    // Pulled next to each other where no crossing is added; the other goes around.
    expect(shapes).toContain("side");
    expect(scene.frames).toEqual([]);
  });

  it("breaks cycles instead of looping and still draws every edge", () => {
    const nodes = ["a", "b", "c"].map((id) => card(id));
    const edges = [edge("a", "b"), edge("b", "c"), edge("c", "a")];
    const scene = layoutCardScene(nodes, edges, OPTIONS);
    expect(scene.edges).toHaveLength(3);
    expect(new Set(scene.cards.map((c) => c.y)).size).toBeGreaterThan(1);
  });

  it("wraps a crowded layer and routes into its lower rows through the gaps beside the cards", () => {
    const nodes = [card("o"), ...["a", "b", "c", "d", "e"].map((id) => card(id))];
    const edges = ["a", "b", "c", "d", "e"].map((id) => edge(id, "o"));
    const scene = layoutCardScene(nodes, edges, { ...OPTIONS, maxPerRow: 2, frames: false });
    expect(new Set(scene.cards.filter((c) => c.id !== "o").map((c) => c.y)).size).toBe(3);
    const lower = scene.edges.filter((e) => e.shape === "loop");
    expect(lower.length).toBeGreaterThan(0);
    // Every orthogonal route stays clear of the cards it does not connect.
    for (const e of lower) {
      for (let i = 1; i < e.points.length; i++) {
        const p = e.points[i - 1];
        const q = e.points[i];
        if (!p || !q) continue;
        const seg = { x: Math.min(p.x, q.x), y: Math.min(p.y, q.y), w: Math.abs(q.x - p.x) || 0.01, h: Math.abs(q.y - p.y) || 0.01 };
        for (const c of scene.cards) {
          if (c.id === e.source || c.id === e.target) continue;
          expect(overlaps(seg, { x: c.x + 1, y: c.y + 1, w: c.w - 2, h: c.h - 2 }), `${e.id} crosses ${c.id}`).toBe(false);
        }
      }
    }
  });

  it("routes long edges through placeholder slots instead of across the cards in between", () => {
    const nodes = ["a", "b", "c", "d", "x"].map((id) => card(id));
    const edges = [edge("b", "a"), edge("c", "b"), edge("d", "c"), edge("d", "a", "depends_on"), edge("x", "c")];
    const scene = layoutCardScene(nodes, edges, OPTIONS);
    const long = scene.edges.find((e) => e.source === "d" && e.target === "a");
    expect(long?.points.length).toBeGreaterThan(2);
  });

  it("makes a frame at least as wide as its title and keeps the cards inside", () => {
    const long = "A group title that is much longer than the single card it frames";
    const scene = layoutCardScene([card("a", 0), card("b", 0)], [edge("b", "a")], {
      ...OPTIONS,
      frameTitle: () => ({ label: long, count: "2 documents" }),
    });
    const frame = scene.frames[0];
    expect(frame?.w).toBeGreaterThan(400);
    const a = byId(scene, "a");
    expect(a.x).toBeGreaterThan(frame?.x ?? 0);
    expect(a.x + a.w).toBeLessThan((frame?.x ?? 0) + (frame?.w ?? 0));
  });

  it("tries each row limit and keeps the one that fits the viewport best", () => {
    const nodes = [card("o"), ...Array.from({ length: 12 }, (_, i) => card(`c${i}`))];
    const edges = nodes.slice(1).map((n) => edge(n.id, "o"));
    const wide = layoutCardScene(nodes, edges, { ...OPTIONS, frames: false, maxPerRow: [3, 12], aspect: 20 });
    const tall = layoutCardScene(nodes, edges, { ...OPTIONS, frames: false, maxPerRow: [3, 12], aspect: 0.6 });
    expect(wide.width).toBeGreaterThan(tall.width);
  });

  it("handles an empty input", () => {
    expect(layoutCardScene([], [], OPTIONS)).toMatchObject({ cards: [], edges: [], frames: [], width: 0, height: 0 });
  });
});
