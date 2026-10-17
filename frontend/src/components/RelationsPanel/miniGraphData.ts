import type { DocType, Neighbourhood } from "../../api";
import { documentCard, relationCardEdge, type CardEdge, type CardNode } from "../graph";

/** Cards of a neighbourhood with the slug of each, for opening a clicked card. */
export function toMiniGraph(
  n: Neighbourhood,
  typeLabel: (docType: DocType | null) => string,
): { cards: CardNode[]; edges: CardEdge[]; slugs: Map<string, string> } {
  const cards = n.nodes.map((node) => documentCard(node, 0, typeLabel));
  const slugs = new Map(n.nodes.map((node) => [node.id, node.slug]));
  return { cards, edges: n.edges.map(relationCardEdge), slugs };
}
