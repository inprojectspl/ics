import type { RelationDirection, RelationItem, RelationList, RelationType } from "../../api";

export interface RelationGroup {
  key: string;
  type: RelationType;
  direction: RelationDirection;
  items: RelationItem[];
}

// Strong, traceability-bearing types first, weak ones last (ADR-0016).
const ORDER: readonly RelationType[] = [
  "supersedes",
  "derived_from",
  "depends_on",
  "part_of",
  "contradicts",
  "duplicates",
  "references",
  "relates_to",
];

/** Groups in display order: by type, outgoing before incoming. */
export function groupRelations(list: RelationList): RelationGroup[] {
  const groups = new Map<string, RelationGroup>();
  const add = (items: RelationItem[] | undefined, direction: RelationDirection) => {
    for (const item of items ?? []) {
      const key = `${item.relation_type}:${direction}`;
      const group = groups.get(key);
      if (group) group.items.push(item);
      else groups.set(key, { key, type: item.relation_type, direction, items: [item] });
    }
  };
  for (const items of Object.values(list.outgoing)) add(items, "out");
  for (const items of Object.values(list.incoming)) add(items, "in");
  const rank = (g: RelationGroup) => ORDER.indexOf(g.type) * 2 + (g.direction === "out" ? 0 : 1);
  return [...groups.values()].sort((a, b) => rank(a) - rank(b));
}

export function countRelations(groups: readonly RelationGroup[]): number {
  let n = 0;
  for (const g of groups) n += g.items.length;
  return n;
}
