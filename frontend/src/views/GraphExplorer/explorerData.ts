/**
 * Loading for the explorer: one query per expansion, keyed like the rest of
 * the app so the reader's mini graph and the project map share the cache.
 */
import { api } from "../../api";
import { RELATION_TYPES } from "../../api/relationTypes";
import type { Neighbourhood, NeighbourhoodNode, ProjectGraph, ProjectSummary } from "../../api/types";
import { qk } from "../../lib/queries";
import { projectNodeId, type DocItem, type Loaded, type ProjectItem, type Source } from "./explorerTree";

// An expansion reads its data again only after this long, so walking back
// and forth does not refetch.
const STALE_MS = 5 * 60_000;

export type SourceData = Neighbourhood | ProjectGraph;

/** Query of one expansion; both shapes are read with `toLoaded`. */
export function sourceQuery(source: Source): {
  queryKey: readonly unknown[];
  queryFn: () => Promise<SourceData>;
  staleTime: number;
} {
  const { slug } = source;
  if (source.kind === "doc") {
    return {
      queryKey: qk.neighbourhood(slug, 1),
      // Every type, content links included, as the reader's mini graph asks.
      queryFn: () => api.getNeighbourhood(slug, { depth: 1, types: RELATION_TYPES }),
      staleTime: STALE_MS,
    };
  }
  return {
    queryKey: qk.projectGraph(slug),
    // The same call as the project map, which shares this cache entry.
    queryFn: () => api.getProjectGraph(slug, { tasks: true }),
    staleTime: STALE_MS,
  };
}

function docItem(n: NeighbourhoodNode | ProjectGraph["nodes"][number], expandable = true): DocItem {
  return {
    kind: "doc",
    id: n.id,
    slug: n.slug,
    title: n.title,
    doc_type: n.doc_type,
    freshness: n.freshness,
    summary: n.summary,
    expandable: "expandable" in n ? n.expandable : expandable,
    external: "external" in n ? n.external : undefined,
  };
}

function isNeighbourhood(data: SourceData): data is Neighbourhood {
  return "root_id" in data;
}

// Cached data objects keep their identity, so every rebuild of the tree reuses one conversion.
const converted = new WeakMap<SourceData, Loaded>();

export function toLoaded(data: SourceData): Loaded {
  let out = converted.get(data);
  if (!out) {
    out = { nodes: data.nodes.map((n) => docItem(n)), edges: data.edges };
    converted.set(data, out);
  }
  return out;
}

/** The root document of a neighbourhood, or null when it is not in the data. */
export function rootItem(data: SourceData | undefined): DocItem | null {
  if (!data || !isNeighbourhood(data)) return null;
  const root = data.nodes.find((n) => n.id === data.root_id);
  return root ? docItem(root) : null;
}

export function projectItem(p: ProjectSummary): ProjectItem {
  return { kind: "project", id: projectNodeId(p.slug), slug: p.slug, name: p.name, documents: p.asset_count };
}
