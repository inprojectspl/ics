/**
 * Pure filtering of the project document graph. Nodes and edges are narrowed
 * together: an edge stays only when its type passes and both ends stay, and a
 * node that keeps no edge moves to the `unlinked` list instead of the canvas.
 */
import type {
  Freshness,
  ProjectGraphNode,
  ProjectTaskLink,
  RelationEdge,
  RelationType,
} from "../../api/types";

/** Doc type filter key of documents without a type. */
export const NO_DOC_TYPE = "";

export interface MapFilters {
  /** Doc type keys to keep (`NO_DOC_TYPE` for untyped); empty keeps all. */
  docTypes: ReadonlySet<string>;
  /** Empty keeps all. */
  freshness: ReadonlySet<Freshness>;
  /** Empty keeps all. */
  relationTypes: ReadonlySet<RelationType>;
  /** Keep only documents linked to a task. */
  onlyTaskDocs: boolean;
  /** Case-insensitive match on title, slug and summary. */
  search: string;
  /** Index into `FilteredGraph.componentSizes`; null shows every graph. */
  component: number | null;
}

export const EMPTY_FILTERS: MapFilters = {
  docTypes: new Set(),
  freshness: new Set(),
  relationTypes: new Set(),
  onlyTaskDocs: false,
  search: "",
  component: null,
};

export interface GraphInput {
  nodes: ProjectGraphNode[];
  edges: RelationEdge[];
  task_links?: ProjectTaskLink[];
}

export interface FilteredGraph {
  /** Drawn on the canvas: nodes with at least one kept edge. */
  nodes: ProjectGraphNode[];
  edges: RelationEdge[];
  /** Nodes that pass the filters but keep no edge; listed beside the canvas. */
  unlinked: ProjectGraphNode[];
  /** Node count of each independent graph among the drawn nodes, largest first. */
  componentSizes: number[];
  /** Independent graph of every drawn node (before `component` narrows them). */
  componentOf: Map<string, number>;
}

function matches(node: ProjectGraphNode, needle: string): boolean {
  if (!needle) return true;
  return [node.title, node.slug, node.summary].some(
    (v) => v != null && v.toLowerCase().includes(needle),
  );
}

function nodePasses(
  node: ProjectGraphNode,
  f: MapFilters,
  needle: string,
  taskDocs: ReadonlySet<string>,
): boolean {
  if (f.docTypes.size > 0 && !f.docTypes.has(node.doc_type ?? NO_DOC_TYPE)) return false;
  if (f.freshness.size > 0 && !f.freshness.has(node.freshness)) return false;
  if (f.onlyTaskDocs && !taskDocs.has(node.id)) return false;
  return matches(node, needle);
}

/** Connected components over undirected edges, numbered by size (largest
 * first, ties by the smallest id so the numbering is stable). */
export function components(
  ids: readonly string[],
  edges: ReadonlyArray<{ source_id: string; target_id: string }>,
): { sizes: number[]; of: Map<string, number> } {
  const parent = new Map<string, string>();
  for (const id of ids) parent.set(id, id);
  const find = (start: string): string => {
    let n = start;
    for (let p = parent.get(n); p !== undefined && p !== n; p = parent.get(n)) {
      const grand = parent.get(p) ?? p;
      parent.set(n, grand);
      n = grand;
    }
    return n;
  };
  for (const e of edges) {
    if (!parent.has(e.source_id) || !parent.has(e.target_id)) continue;
    const a = find(e.source_id);
    const b = find(e.target_id);
    if (a !== b) parent.set(a, b);
  }
  const groups = new Map<string, string[]>();
  for (const id of ids) {
    const root = find(id);
    const list = groups.get(root);
    if (list) list.push(id);
    else groups.set(root, [id]);
  }
  const ordered = [...groups.values()]
    .map((g) => ({ g, min: g.reduce((m, id) => (id < m ? id : m)) }))
    .sort((x, y) => y.g.length - x.g.length || (x.min < y.min ? -1 : 1));
  const of = new Map<string, number>();
  for (const [i, { g }] of ordered.entries()) for (const id of g) of.set(id, i);
  return { sizes: ordered.map(({ g }) => g.length), of };
}

export function filterGraph(graph: GraphInput, filters: MapFilters): FilteredGraph {
  const needle = filters.search.trim().toLowerCase();
  const taskDocs = new Set((graph.task_links ?? []).map((l) => l.asset_id));
  const kept = graph.nodes.filter((n) => nodePasses(n, filters, needle, taskDocs));
  const keptIds = new Set(kept.map((n) => n.id));
  const edges = graph.edges.filter(
    (e) =>
      (filters.relationTypes.size === 0 || filters.relationTypes.has(e.relation_type)) &&
      keptIds.has(e.source_id) &&
      keptIds.has(e.target_id),
  );
  const linked = new Set<string>();
  for (const e of edges) {
    linked.add(e.source_id);
    linked.add(e.target_id);
  }
  const drawn = kept.filter((n) => linked.has(n.id));
  const unlinked = kept.filter((n) => !linked.has(n.id));
  const { sizes, of } = components(
    drawn.map((n) => n.id),
    edges,
  );
  const pick = filters.component;
  if (pick === null || pick < 0 || pick >= sizes.length) {
    return { nodes: drawn, edges, unlinked, componentSizes: sizes, componentOf: of };
  }
  return {
    nodes: drawn.filter((n) => of.get(n.id) === pick),
    edges: edges.filter((e) => of.get(e.source_id) === pick),
    unlinked,
    componentSizes: sizes,
    componentOf: of,
  };
}
