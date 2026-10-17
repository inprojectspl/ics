import { describe, expect, it } from "vitest";

import { toGraph } from "./graphData";

describe("toGraph", () => {
  it("keys nodes by path and keeps payload fields for the hover panel", () => {
    const g = toGraph({
      nodes: [{ path: "a.md", title: "A", in_degree: 2, out_degree: 1 }],
      edges: [{ from: "a.md", to: "b.md" }],
    });
    expect(g.nodes).toEqual([
      { path: "a.md", title: "A", in_degree: 2, out_degree: 1, id: "a.md", label: "A", degree: 3 },
    ]);
    expect(g.edges).toEqual([{ source: "a.md", target: "b.md" }]);
  });
});
