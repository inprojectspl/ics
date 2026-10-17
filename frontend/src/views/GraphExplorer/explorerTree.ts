/**
 * The explored graph as a tree of expansions in the order the reader made
 * them. A node belongs to the expansion that found it first; other relations
 * between cards are cross edges.
 */
import type { DocType, Freshness, RelationEdge, RelationType } from "../../api/types";

/** At most this many children are shown per node; the rest wait behind a "more" card. */
export const CHILD_PAGE = 12;

/** What an expansion loads: a document's neighbourhood or a project's graph. */
export type Source = { kind: "doc"; slug: string } | { kind: "project"; slug: string };

export interface Expansion {
  id: string;
  source: Source;
}

export interface DocItem {
  kind: "doc";
  id: string;
  slug: string;
  title: string | null;
  doc_type: DocType | null;
  freshness: Freshness;
  summary: string | null;
  /** The viewer may load its neighbourhood. */
  expandable: boolean;
  external?: boolean;
}

export interface ProjectItem {
  kind: "project";
  id: string;
  slug: string;
  name: string;
  documents: number;
}

interface MoreItem {
  kind: "more";
  id: string;
  /** Children still hidden behind this card. */
  hidden: number;
}

export type ExplorerItem = DocItem | ProjectItem | MoreItem;

/** Data of one expansion: the nodes found around the expanded node and the edges among them. */
export interface Loaded {
  nodes: DocItem[];
  edges: RelationEdge[];
}

export interface TreeNode {
  item: ExplorerItem;
  parent: string | null;
  depth: number;
  children: string[];
  /** The relation that made it a child; null for roots, project members and "more" cards. */
  via: RelationEdge | null;
  expanded: boolean;
}

export interface TreeEdge {
  id: string;
  source: string;
  target: string;
  /** A parent to child link; otherwise a quiet cross edge. */
  tree: boolean;
  /** Null for the project to member link. */
  relation: RelationEdge | null;
}

export interface ExploredTree {
  nodes: Map<string, TreeNode>;
  roots: string[];
  edges: TreeEdge[];
}

export interface TreeInput {
  roots: readonly ExplorerItem[];
  expansions: readonly Expansion[];
  loaded: ReadonlyMap<string, Loaded>;
  /** Extra pages of children revealed per node. */
  reveal: Readonly<Record<string, number>>;
  /** Children shown whatever the page: the steps of a walk to a search result. */
  pinned?: ReadonlySet<string>;
  /** Relation types followed and drawn. */
  types: ReadonlySet<RelationType>;
}

const PROJECT_PREFIX = "project:";
const MORE_PREFIX = "more:";

export function projectNodeId(slug: string): string {
  return PROJECT_PREFIX + slug;
}

export function moreNodeId(parent: string): string {
  return MORE_PREFIX + parent;
}

/** Parent of a "more" card id, or null for any other id. */
export function moreParent(id: string): string | null {
  return id.startsWith(MORE_PREFIX) ? id.slice(MORE_PREFIX.length) : null;
}

export function sourceOf(item: ExplorerItem): Source | null {
  if (item.kind === "doc") return item.expandable ? { kind: "doc", slug: item.slug } : null;
  if (item.kind === "project") return { kind: "project", slug: item.slug };
  return null;
}

/** Candidate children of an expanded node, in the order the data lists them. */
function candidates(
  id: string,
  data: Loaded,
  nodes: ReadonlyMap<string, TreeNode>,
  types: ReadonlySet<RelationType>,
  project: boolean,
): Array<{ item: DocItem; via: RelationEdge | null }> {
  if (project) {
    return data.nodes.filter((n) => !n.external && !nodes.has(n.id)).map((item) => ({ item, via: null }));
  }
  const via = new Map<string, RelationEdge>();
  for (const e of data.edges) {
    if (!types.has(e.relation_type)) continue;
    const other = e.source_id === id ? e.target_id : e.target_id === id ? e.source_id : null;
    if (other && other !== id && !via.has(other)) via.set(other, e);
  }
  const out: Array<{ item: DocItem; via: RelationEdge | null }> = [];
  for (const n of data.nodes) {
    const edge = via.get(n.id);
    if (edge && !nodes.has(n.id)) out.push({ item: n, via: edge });
  }
  return out;
}

export function buildTree(input: TreeInput): ExploredTree {
  const nodes = new Map<string, TreeNode>();
  const roots: string[] = [];
  for (const item of input.roots) {
    if (nodes.has(item.id)) continue;
    nodes.set(item.id, { item, parent: null, depth: 0, children: [], via: null, expanded: false });
    roots.push(item.id);
  }
  for (const exp of input.expansions) {
    const node = nodes.get(exp.id);
    const data = input.loaded.get(exp.id);
    // Off the canvas (filtered out) or not loaded yet: it waits, its place in the order kept.
    if (!node || !data || node.expanded) continue;
    node.expanded = true;
    const found = candidates(exp.id, data, nodes, input.types, node.item.kind === "project");
    const page = CHILD_PAGE * (1 + (input.reveal[exp.id] ?? 0));
    const shown = found.filter((c, i) => i < page || input.pinned?.has(c.item.id));
    for (const c of shown) {
      nodes.set(c.item.id, { item: c.item, parent: exp.id, depth: node.depth + 1, children: [], via: c.via, expanded: false });
      node.children.push(c.item.id);
    }
    const hidden = found.length - shown.length;
    if (hidden > 0) {
      const id = moreNodeId(exp.id);
      nodes.set(id, { item: { kind: "more", id, hidden }, parent: exp.id, depth: node.depth + 1, children: [], via: null, expanded: false });
      node.children.push(id);
    }
  }
  return { nodes, roots, edges: treeEdges(nodes, input) };
}

function treeEdges(nodes: ReadonlyMap<string, TreeNode>, input: TreeInput): TreeEdge[] {
  const edges: TreeEdge[] = [];
  const seen = new Set<string>();
  for (const [id, n] of nodes) {
    if (n.parent === null || n.via || n.item.kind !== "doc") continue;
    edges.push({ id: `${n.parent}>${id}`, source: n.parent, target: id, tree: true, relation: null });
  }
  for (const data of input.loaded.values()) {
    for (const e of data.edges) {
      if (seen.has(e.id) || !input.types.has(e.relation_type)) continue;
      const a = nodes.get(e.source_id);
      const b = nodes.get(e.target_id);
      if (!a || !b || e.source_id === e.target_id) continue;
      seen.add(e.id);
      const tree = a.via?.id === e.id || b.via?.id === e.id;
      edges.push({ id: e.id, source: e.source_id, target: e.target_id, tree, relation: e });
    }
  }
  return edges;
}

/** Ids of a node's subtree, the node included. */
export function subtreeOf(tree: ExploredTree, id: string): string[] {
  const out: string[] = [];
  const stack = [id];
  while (stack.length) {
    const cur = stack.pop();
    if (cur === undefined) break;
    const n = tree.nodes.get(cur);
    if (!n) continue;
    out.push(cur);
    stack.push(...n.children);
  }
  return out;
}

/** Ids from the node up to its root, the node included. */
export function ancestorsOf(tree: ExploredTree, id: string | null): string[] {
  const out: string[] = [];
  let cur = id === null ? undefined : tree.nodes.get(id);
  let curId = id;
  while (cur && curId !== null) {
    out.push(curId);
    curId = cur.parent;
    cur = curId === null ? undefined : tree.nodes.get(curId);
  }
  return out;
}

/** Address of an item in the app: the document or the project page. */
export function itemHref(item: DocItem | ProjectItem): string {
  return item.kind === "project" ? `/projects/${item.slug}` : `/v/${item.slug}`;
}

/** Display name of an item. */
export function itemTitle(item: DocItem | ProjectItem): string {
  return item.kind === "project" ? item.name : item.title || item.slug;
}
