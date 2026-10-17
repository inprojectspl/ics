import type { GraphEdge } from "../graph";
import type { GraphPayload, VaultNode } from "./types";

/** Maps the wikilink graph payload onto plain engine nodes and edges. */
export function toGraph(payload: GraphPayload): { nodes: VaultNode[]; edges: GraphEdge[] } {
  return {
    nodes: payload.nodes.map((n) => ({
      ...n,
      id: n.path,
      label: n.title,
      degree: n.in_degree + n.out_degree,
    })),
    edges: payload.edges.map((e) => ({ source: e.from, target: e.to })),
  };
}
