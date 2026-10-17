import { describe, expect, it } from "vitest";

import { collapse, enforceBudget, expand, initialState, revealMore, touch, walk, type ExplorerState } from "./explorerState";
import { buildTree, type ExploredTree, type Loaded } from "./explorerTree";
import { ALL, doc, star } from "./testData";

const src = (id: string) => ({ id, source: { kind: "doc" as const, slug: `s${id}` } });

// a has children b and c; b has b1..b3, c has c1..c3.
const loaded = new Map<string, Loaded>([
  ["a", star("a", ["b", "c"])],
  ["b", star("b", ["b1", "b2", "b3"])],
  ["c", star("c", ["c1", "c2", "c3"])],
]);
const treeOf = (s: ExplorerState): ExploredTree =>
  buildTree({ roots: [doc("a")], expansions: s.expansions, loaded, reveal: s.reveal, types: ALL });

describe("explorer state", () => {
  it("opens a walk in order, pins every step after the first, and drops pins with a collapse", () => {
    const s = walk(expand(initialState(), src("a")), [src("a"), src("b")], "b2");
    expect(s.expansions.map((e) => e.id)).toEqual(["a", "b"]);
    expect(new Set(s.pinned)).toEqual(new Set(["b", "b2"]));
    const tree = buildTree({ roots: [doc("a")], expansions: s.expansions, loaded, reveal: s.reveal, pinned: new Set(s.pinned), types: ALL });
    // b keeps its own pin when it folds; what was under it goes.
    expect(collapse(s, tree, "b").pinned).toEqual(["b"]);
  });

  it("expands once and records the use", () => {
    const s = expand(expand(initialState(), src("a")), src("a"));
    expect(s.expansions.map((e) => e.id)).toEqual(["a"]);
    expect(s.used.a).toBe(s.clock);
  });

  it("collapses the subtree's expansions with the node", () => {
    const s = expand(expand(expand(initialState(), src("a")), src("b")), src("c"));
    const next = collapse(s, treeOf(s), "a");
    expect(next.expansions).toEqual([]);
    expect(next.used).toEqual({});
    const onlyB = collapse(s, treeOf(s), "b");
    expect(onlyB.expansions.map((e) => e.id)).toEqual(["a", "c"]);
  });

  it("counts revealed pages and touches ancestors", () => {
    const s = expand(expand(initialState(), src("a")), src("b"));
    expect(revealMore(revealMore(s, "b"), "b").reveal.b).toBe(2);
    const touched = touch(s, treeOf(s), "b1");
    expect(touched.used.b).toBe(touched.clock);
    expect(touched.used.a).toBe(touched.clock);
  });

  it("collapses the least recently used branch past the budget", () => {
    let s = initialState([src("a")]);
    s = expand(s, src("b"));
    s = expand(s, src("c"));
    // 9 cards: a, b, c, b1..b3, c1..c3. A budget of 6 drops one branch: b is older.
    const { state, collapsed } = enforceBudget(s, treeOf, ["c"], 6);
    expect(collapsed).toEqual(["b"]);
    expect(state.evicted).toBe(1);
    expect(treeOf(state).nodes.size).toBe(6);
  });

  it("keeps the branches that hold the selection", () => {
    let s = initialState([src("a")]);
    s = expand(s, src("b"));
    s = expand(s, src("c"));
    // b is the oldest, but the selection is inside it.
    const { collapsed } = enforceBudget(s, treeOf, ["b2", "c"], 6);
    expect(collapsed).toEqual([]);
  });

  it("leaves a tree within the budget alone", () => {
    const s = initialState([src("a")]);
    const out = enforceBudget(s, treeOf, [null]);
    expect(out.collapsed).toEqual([]);
    expect(out.state.expansions).toEqual(s.expansions);
  });
});
