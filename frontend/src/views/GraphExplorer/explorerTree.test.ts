import { describe, expect, it } from "vitest";

import { ancestorsOf, buildTree, CHILD_PAGE, moreNodeId, moreParent, subtreeOf, type Loaded } from "./explorerTree";
import { ALL, doc, project, rel, star } from "./testData";

const docSource = (slug: string) => ({ kind: "doc" as const, slug });

describe("buildTree", () => {
  it("attaches a node to the expansion that found it first", () => {
    const loaded = new Map<string, Loaded>([
      ["a", star("a", ["b", "c"])],
      ["b", { nodes: [doc("b"), doc("c"), doc("d")], edges: [rel("b-c", "b", "c"), rel("d-b", "d", "b")] }],
    ]);
    const tree = buildTree({
      roots: [doc("a")],
      expansions: [
        { id: "a", source: docSource("sa") },
        { id: "b", source: docSource("sb") },
      ],
      loaded,
      reveal: {},
      types: ALL,
    });
    expect(tree.nodes.get("a")?.children).toEqual(["b", "c"]);
    // c was already a child of a, so b only adds d.
    expect(tree.nodes.get("b")?.children).toEqual(["d"]);
    expect(tree.nodes.get("d")?.depth).toBe(2);
    const cross = tree.edges.find((e) => e.id === "b-c");
    expect(cross?.tree).toBe(false);
    expect(tree.edges.find((e) => e.id === "d-b")?.tree).toBe(true);
  });

  it("puts children past the page behind a more card and reveals the next page", () => {
    const others = Array.from({ length: CHILD_PAGE + 5 }, (_, i) => `n${i}`);
    const input = {
      roots: [doc("a")],
      expansions: [{ id: "a", source: docSource("sa") }],
      loaded: new Map([["a", star("a", others)]]),
      reveal: {},
      types: ALL,
    };
    const first = buildTree(input);
    const children = first.nodes.get("a")?.children ?? [];
    expect(children).toHaveLength(CHILD_PAGE + 1);
    expect(children.at(-1)).toBe(moreNodeId("a"));
    const more = first.nodes.get(moreNodeId("a"))?.item;
    expect(more?.kind === "more" && more.hidden).toBe(5);
    expect(moreParent(moreNodeId("a"))).toBe("a");

    const second = buildTree({ ...input, reveal: { a: 1 } });
    expect(second.nodes.get("a")?.children).toHaveLength(CHILD_PAGE + 5);
    expect(second.nodes.has(moreNodeId("a"))).toBe(false);
  });

  it("keeps a pinned child on the canvas past its parent's page", () => {
    const others = Array.from({ length: CHILD_PAGE + 5 }, (_, i) => `n${i}`);
    const data = new Map<string, Loaded>([["a", star("a", others)]]);
    const last = `n${CHILD_PAGE + 4}`;
    const tree = buildTree({
      roots: [doc("a")],
      expansions: [{ id: "a", source: { kind: "doc", slug: "sa" } }],
      loaded: data,
      reveal: {},
      pinned: new Set([last]),
      types: ALL,
    });
    const children = tree.nodes.get("a")?.children ?? [];
    expect(children).toContain(last);
    const more = tree.nodes.get(moreNodeId("a"))?.item;
    expect(more?.kind === "more" && more.hidden).toBe(4);
  });

  it("follows only the relation types in the filter", () => {
    const loaded = new Map<string, Loaded>([
      ["a", { nodes: [doc("a"), doc("b"), doc("c")], edges: [rel("ab", "a", "b", "depends_on"), rel("ac", "a", "c", "references")] }],
    ]);
    const tree = buildTree({
      roots: [doc("a")],
      expansions: [{ id: "a", source: docSource("sa") }],
      loaded,
      reveal: {},
      types: new Set(["depends_on"]),
    });
    expect(tree.nodes.get("a")?.children).toEqual(["b"]);
    expect(tree.edges.map((e) => e.id)).toEqual(["ab"]);
  });

  it("lists a project's own documents as its children, linked by a project edge", () => {
    const loaded = new Map<string, Loaded>([
      ["project:p", { nodes: [doc("a"), doc("b"), doc("x", { external: true })], edges: [rel("ab", "a", "b")] }],
    ]);
    const tree = buildTree({
      roots: [project("p")],
      expansions: [{ id: "project:p", source: { kind: "project", slug: "p" } }],
      loaded,
      reveal: {},
      types: ALL,
    });
    expect(tree.nodes.get("project:p")?.children).toEqual(["a", "b"]);
    expect(tree.edges.filter((e) => e.relation === null).map((e) => e.target)).toEqual(["a", "b"]);
    // Siblings under a project are tied by a cross edge.
    expect(tree.edges.find((e) => e.id === "ab")?.tree).toBe(false);
  });

  it("skips an expansion whose node is not on the canvas", () => {
    const tree = buildTree({
      roots: [doc("a")],
      expansions: [{ id: "z", source: docSource("sz") }],
      loaded: new Map([["z", star("z", ["y"])]]),
      reveal: {},
      types: ALL,
    });
    expect([...tree.nodes.keys()]).toEqual(["a"]);
  });

  it("walks subtrees and ancestors", () => {
    const loaded = new Map<string, Loaded>([
      ["a", star("a", ["b"])],
      ["b", star("b", ["c"])],
    ]);
    const tree = buildTree({
      roots: [doc("a")],
      expansions: [
        { id: "a", source: docSource("sa") },
        { id: "b", source: docSource("sb") },
      ],
      loaded,
      reveal: {},
      types: ALL,
    });
    expect(subtreeOf(tree, "b").sort()).toEqual(["b", "c"]);
    expect(ancestorsOf(tree, "c")).toEqual(["c", "b", "a"]);
    expect(ancestorsOf(tree, null)).toEqual([]);
  });
});
