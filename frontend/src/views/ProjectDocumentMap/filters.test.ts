import { describe, expect, it } from "vitest";

import type { ProjectGraphNode, RelationEdge, RelationType } from "../../api/types";
import { EMPTY_FILTERS, NO_DOC_TYPE, components, filterGraph, type MapFilters } from "./filters";

function node(id: string, over: Partial<ProjectGraphNode> = {}): ProjectGraphNode {
  return {
    id,
    slug: `s${id}`,
    title: `Doc ${id}`,
    kind: "md_file",
    doc_type: "design",
    freshness: "current",
    summary: null,
    estimated_tokens: null,
    superseded_by: null,
    content_updated_at: null,
    external: false,
    ...over,
  } as ProjectGraphNode;
}

function edge(id: string, source: string, target: string, type: RelationType = "references"): RelationEdge {
  return {
    id,
    relation_type: type,
    source_id: source,
    target_id: target,
    source_path: null,
    target_path: null,
    target_anchor: null,
    target_version: null,
    target_version_now: null,
    target_changed: false,
    note: null,
    origin: "manual",
    created_at: null,
  };
}

// Two graphs (a-b-c, d-e) and a document without relations (f).
const graph = {
  nodes: [
    node("a", { doc_type: "requirements" }),
    node("b", { freshness: "review_overdue", summary: "Payment flow" }),
    node("c", { doc_type: null }),
    node("d"),
    node("e", { freshness: "superseded" }),
    node("f"),
  ],
  edges: [
    edge("ab", "b", "a", "derived_from"),
    edge("bc", "b", "c"),
    edge("de", "d", "e", "supersedes"),
  ],
  task_links: [{ task_id: "op:work_package:1", asset_id: "b", role: "context", required: false }],
};

const with_ = (over: Partial<MapFilters>): MapFilters => ({ ...EMPTY_FILTERS, ...over });
const ids = (xs: Array<{ id: string }>) => xs.map((x) => x.id).sort();

/** Every drawn edge has both ends drawn, and every drawn node has an edge. */
function expectConsistent(r: ReturnType<typeof filterGraph>) {
  const drawn = new Set(r.nodes.map((n) => n.id));
  for (const e of r.edges) {
    expect(drawn.has(e.source_id)).toBe(true);
    expect(drawn.has(e.target_id)).toBe(true);
  }
  const touched = new Set(r.edges.flatMap((e) => [e.source_id, e.target_id]));
  for (const n of r.nodes) expect(touched.has(n.id)).toBe(true);
  for (const n of r.unlinked) expect(drawn.has(n.id)).toBe(false);
}

describe("filterGraph", () => {
  it("draws linked documents and lists the ones without relations", () => {
    const r = filterGraph(graph, EMPTY_FILTERS);
    expect(ids(r.nodes)).toEqual(["a", "b", "c", "d", "e"]);
    expect(ids(r.unlinked)).toEqual(["f"]);
    expect(r.edges).toHaveLength(3);
    expect(r.componentSizes).toEqual([3, 2]);
    expectConsistent(r);
  });

  it("drops edges whose end is filtered out and moves orphans to the list", () => {
    const r = filterGraph(graph, with_({ docTypes: new Set(["design"]) }));
    // a (requirements) and c (untyped) go; b keeps no edge.
    expect(ids(r.nodes)).toEqual(["d", "e"]);
    expect(ids(r.unlinked)).toEqual(["b", "f"]);
    expectConsistent(r);
  });

  it("keeps untyped documents under the no-type key", () => {
    const r = filterGraph(graph, with_({ docTypes: new Set([NO_DOC_TYPE, "design"]) }));
    expect(ids(r.nodes)).toEqual(["b", "c", "d", "e"]);
    expectConsistent(r);
  });

  it("narrows by relation type without dropping the documents", () => {
    const r = filterGraph(graph, with_({ relationTypes: new Set<RelationType>(["derived_from"]) }));
    expect(ids(r.edges)).toEqual(["ab"]);
    expect(ids(r.nodes)).toEqual(["a", "b"]);
    expect(ids(r.unlinked)).toEqual(["c", "d", "e", "f"]);
    expectConsistent(r);
  });

  it("filters by freshness, search and task documents", () => {
    expect(ids(filterGraph(graph, with_({ freshness: new Set(["superseded"]) })).unlinked)).toEqual([
      "e",
    ]);
    const search = filterGraph(graph, with_({ search: "  PAYMENT " }));
    expect(ids(search.unlinked)).toEqual(["b"]);
    expect(search.nodes).toEqual([]);
    const tasks = filterGraph(graph, with_({ onlyTaskDocs: true }));
    expect(ids(tasks.unlinked)).toEqual(["b"]);
    expectConsistent(tasks);
  });

  it("shows one independent graph when picked, and all for an unknown pick", () => {
    const second = filterGraph(graph, with_({ component: 1 }));
    expect(ids(second.nodes)).toEqual(["d", "e"]);
    expect(ids(second.edges)).toEqual(["de"]);
    expect(second.componentSizes).toEqual([3, 2]);
    expectConsistent(second);
    expect(filterGraph(graph, with_({ component: 7 })).nodes).toHaveLength(5);
  });
});

describe("components", () => {
  it("numbers graphs by size with a stable tie-break", () => {
    const r = components(["x", "y", "z", "w"], [
      { source_id: "z", target_id: "w" },
      { source_id: "x", target_id: "y" },
    ]);
    expect(r.sizes).toEqual([2, 2]);
    expect(r.of.get("w")).toBe(0);
    expect(r.of.get("x")).toBe(1);
  });
});
