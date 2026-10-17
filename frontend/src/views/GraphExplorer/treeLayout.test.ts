import { describe, expect, it } from "vitest";

import type { PlacedCard } from "../../components/graph/cardTypes";
import { buildTree, type Expansion, type Loaded } from "./explorerTree";
import { ALL, doc, project, rel, star } from "./testData";
import { layoutTree, MIN_WRAP, WRAP, wrapFor } from "./treeLayout";

const SIZE = { w: 200, h: 60 };
const src = (id: string): Expansion => ({ id, source: { kind: "doc", slug: `s${id}` } });

const loaded = new Map<string, Loaded>([
  ["a", { nodes: [doc("a"), doc("b"), doc("c"), doc("d")], edges: [rel("ab", "a", "b"), rel("ca", "c", "a"), rel("ad", "a", "d"), rel("bd", "b", "d")] }],
  ["b", star("b", ["b1", "b2", "b3"])],
  ["d", star("d", ["d1", "d2"])],
]);

function scene(expansions: Expansion[], direction: "right" | "down" = "right") {
  const tree = buildTree({ roots: [doc("a"), project("p")], expansions, loaded, reveal: {}, types: ALL });
  return layoutTree(tree, {
    size: SIZE,
    density: "normal",
    direction,
    card: (id) => ({ id, title: id, color: "#000", component: 0 }),
    edgeStyle: (e) => ({ kind: e.relation?.relation_type ?? "project", width: 1 }),
  });
}

const byId = (cards: PlacedCard[]) => new Map(cards.map((c) => [c.id, c]));

function overlaps(a: PlacedCard, b: PlacedCard): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

describe("layoutTree", () => {
  it("places a column per depth, left to right", () => {
    const s = scene([src("a"), src("b")]);
    const cards = byId(s.cards);
    expect(s.direction).toBe("right");
    expect(cards.get("a")?.x).toBe(0);
    expect(cards.get("b")?.x).toBe(cards.get("c")?.x);
    expect((cards.get("b1")?.x ?? 0) > (cards.get("b")?.x ?? 0)).toBe(true);
  });

  it("centres a parent on its children", () => {
    const cards = byId(scene([src("a"), src("b")]).cards);
    const b1 = cards.get("b1")?.y ?? 0;
    const b3 = cards.get("b3")?.y ?? 0;
    expect(cards.get("b")?.y).toBe((b1 + b3) / 2);
  });

  it("keeps the cards above an expansion in place when it adds children", () => {
    const before = byId(scene([src("a"), src("b")]).cards);
    const after = byId(scene([src("a"), src("b"), src("d")]).cards);
    // b's subtree comes before d in the tree order: none of it moves.
    for (const id of ["b", "b1", "b2", "b3", "c"]) expect(after.get(id)).toEqual(before.get(id));
    // Every card keeps its column.
    for (const [id, card] of before) expect(after.get(id)?.x).toBe(card.x);
  });

  it("never overlaps two cards", () => {
    const cards = scene([src("a"), src("b"), src("d")]).cards;
    for (let i = 0; i < cards.length; i++) {
      for (let j = i + 1; j < cards.length; j++) {
        const a = cards[i];
        const b = cards[j];
        if (a && b) expect(overlaps(a, b), `${a.id} / ${b.id}`).toBe(false);
      }
    }
  });

  it("draws tree edges as flows between the facing sides and cross edges quiet", () => {
    const s = scene([src("a"), src("b"), src("d")]);
    const cards = byId(s.cards);
    const ab = s.edges.find((e) => e.id === "ab");
    expect(ab?.shape).toBe("flow");
    expect(ab?.quiet).toBe(false);
    const a = cards.get("a");
    expect(ab?.points[0]).toEqual({ x: (a?.x ?? 0) + SIZE.w, y: (a?.y ?? 0) + SIZE.h / 2 });
    // c -> a runs against the tree: it starts at c's left side.
    const ca = s.edges.find((e) => e.id === "ca");
    const c = cards.get("c");
    expect(ca?.points[0]).toEqual({ x: c?.x, y: (c?.y ?? 0) + SIZE.h / 2 });
    // b and d are siblings: a quiet loop beside their column.
    const bd = s.edges.find((e) => e.id === "bd");
    expect(bd?.quiet).toBe(true);
    expect(bd?.shape).toBe("loop");
    // Quiet edges are drawn first, under the tree.
    const firstTree = s.edges.findIndex((e) => !e.quiet);
    expect(s.edges.slice(firstTree).every((e) => !e.quiet)).toBe(true);
  });

  it("top down: a row per depth, siblings side by side, parent centred above, no overlaps", () => {
    const s = scene([src("a"), src("b"), src("d")], "down");
    const cards = byId(s.cards);
    expect(s.direction).toBe("down");
    expect(cards.get("a")?.y).toBe(0);
    expect(cards.get("b")?.y).toBe(cards.get("c")?.y);
    expect((cards.get("b1")?.y ?? 0) > (cards.get("b")?.y ?? 0)).toBe(true);
    const b1 = cards.get("b1")?.x ?? 0;
    const b3 = cards.get("b3")?.x ?? 0;
    expect(cards.get("b")?.x).toBe((b1 + b3) / 2);
    const all = s.cards;
    for (let i = 0; i < all.length; i++) {
      for (let j = i + 1; j < all.length; j++) {
        const a = all[i];
        const b = all[j];
        if (a && b) expect(overlaps(a, b), `${a.id} / ${b.id}`).toBe(false);
      }
    }
    // Tree edges leave the parent's bottom and enter the child's top.
    const ab = s.edges.find((e) => e.id === "ab");
    const a = cards.get("a");
    const b = cards.get("b");
    expect(ab?.points[0]).toEqual({ x: (a?.x ?? 0) + SIZE.w / 2, y: (a?.y ?? 0) + SIZE.h });
    expect(ab?.points[1]).toEqual({ x: (b?.x ?? 0) + SIZE.w / 2, y: b?.y });
    expect(s.edges.find((e) => e.id === "bd")?.shape).toBe("loop");
  });

  it("wraps many leaves of one parent into lines of WRAP, without overlaps", () => {
    const kids = Array.from({ length: WRAP + 3 }, (_, i) => `k${i}`);
    const many = new Map<string, Loaded>([["a", star("a", kids)]]);
    for (const direction of ["down", "right"] as const) {
      const tree = buildTree({ roots: [doc("a")], expansions: [src("a")], loaded: many, reveal: {}, types: ALL });
      const s = layoutTree(tree, {
        size: SIZE,
        density: "normal",
        direction,
        card: (id) => ({ id, title: id, color: "#000", component: 0 }),
        edgeStyle: (e) => ({ kind: e.relation?.relation_type ?? "project", width: 1 }),
      });
      const cards = byId(s.cards);
      const main = (id: string) => (direction === "down" ? cards.get(id)?.y : cards.get(id)?.x) ?? 0;
      const side = (id: string) => (direction === "down" ? cards.get(id)?.x : cards.get(id)?.y) ?? 0;
      // The first WRAP share a line, the rest start the next one under the first.
      expect(main(`k${WRAP - 1}`)).toBe(main("k0"));
      expect(main(`k${WRAP}`)).toBeGreaterThan(main("k0"));
      expect(side(`k${WRAP}`)).toBe(side("k0"));
      for (let i = 0; i < s.cards.length; i++) {
        for (let j = i + 1; j < s.cards.length; j++) {
          const p = s.cards[i];
          const q = s.cards[j];
          if (p && q) expect(overlaps(p, q), `${direction} ${p.id} / ${q.id}`).toBe(false);
        }
      }
    }
  });

  it("wraps to what fits the canvas at a readable zoom, between MIN_WRAP and WRAP", () => {
    const card = { w: 216, h: 96 };
    // A phone: two side by side, not six tiles.
    expect(wrapFor("down", { w: 360, h: 600 }, card)).toBe(MIN_WRAP);
    expect(wrapFor("down", { w: 1000, h: 800 }, card)).toBe(5);
    expect(wrapFor("down", { w: 3000, h: 800 }, card)).toBe(WRAP);
    // Growing right, the height decides.
    expect(wrapFor("right", { w: 360, h: 600 }, card)).toBe(5);
    // Not measured yet.
    expect(wrapFor("down", { w: 0, h: 0 }, card)).toBe(WRAP);
  });
});
