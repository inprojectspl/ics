import { describe, expect, it } from "vitest";

import { countCrossings } from "./layered";
import type { GraphEdge } from "./types";

const derived = (source: string, target: string): GraphEdge => ({
  source,
  target,
  kind: "derived_from",
});

describe("countCrossings", () => {
  it("counts crossing segments between adjacent layers", () => {
    const layers = [
      ["a", "b"],
      ["c", "d"],
    ];
    expect(countCrossings(layers, [derived("c", "a"), derived("d", "b")])).toBe(0);
    expect(countCrossings(layers, [derived("d", "a"), derived("c", "b")])).toBe(1);
  });

  it("ignores edges sharing an endpoint and within one layer", () => {
    const layers = [["a", "b"], ["c"]];
    expect(countCrossings(layers, [derived("c", "a"), derived("c", "b")])).toBe(0);
    expect(countCrossings(layers, [derived("a", "b"), derived("c", "a")])).toBe(0);
  });

  it("counts crossings of edges spanning several layers", () => {
    const layers = [["a", "x"], ["m1", "m2"], ["b", "y"]];
    // a(0,0) -> y(2,1) crosses x(0,1) -> b(2,0) in the middle column.
    expect(countCrossings(layers, [derived("y", "a"), derived("b", "x")])).toBe(1);
  });
});
