import { patchJson, postJson, req } from "./_core";
import type {
  AddExternalRefBody,
  AddRelationBody,
  AssetOutline,
  ContextInclude,
  ContextPack,
  ContextSystem,
  ExternalRef,
  GraphPath,
  Neighbourhood,
  PatchRelationBody,
  RelationEdge,
  RelationList,
  RelationType,
} from "./types";

export interface RelationListOpts {
  types?: RelationType[];
  direction?: "both" | "out" | "in";
}

export interface NeighbourhoodOpts {
  /** 1 to 3; the server default is 1. The node cap stays at the server default. */
  depth?: number;
  /** Types to follow; the server default is the strong ones (no content links). */
  types?: readonly RelationType[];
}

function query(params: URLSearchParams): string {
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export const listRelations = (slug: string, opts: RelationListOpts = {}) => {
  const q = new URLSearchParams();
  for (const type of opts.types ?? []) q.append("types", type);
  if (opts.direction && opts.direction !== "both") q.set("direction", opts.direction);
  return req<RelationList>(`/api/assets/by-slug/${slug}/relations${query(q)}`);
};

export const getNeighbourhood = (slug: string, opts: NeighbourhoodOpts = {}) => {
  const q = new URLSearchParams();
  if (opts.depth) q.set("depth", String(opts.depth));
  for (const type of opts.types ?? []) q.append("types", type);
  return req<Neighbourhood>(`/api/assets/by-slug/${slug}/neighbourhood${query(q)}`);
};

export interface GraphPathOpts {
  /** Ids of documents already on screen. */
  from?: readonly string[];
  /** Slugs of projects already on screen. */
  projects?: readonly string[];
  /** Types to walk; the server default is every type. */
  types?: readonly RelationType[];
}

/** A POST: the documents on screen do not fit a URL. */
export const findGraphPath = (slug: string, opts: GraphPathOpts = {}) =>
  postJson<GraphPath>(`/api/assets/by-slug/${slug}/path`, {
    from: opts.from ?? [],
    projects: opts.projects ?? [],
    types: opts.types ?? null,
  });

export const addRelation = (assetId: string, body: AddRelationBody) =>
  postJson<RelationEdge>(`/api/assets/${assetId}/relations`, body);

export const patchRelation = (relationId: string, body: PatchRelationBody) =>
  patchJson<RelationEdge>(`/api/relations/${relationId}`, body);

export const deleteRelation = (relationId: string) =>
  req<{ deleted: true }>(`/api/relations/${relationId}`, { method: "DELETE" });

export const getOutline = (slug: string) => req<AssetOutline>(`/api/assets/by-slug/${slug}/outline`);

// ---------- Task links (ADR-0018) ----------

export const listExternalRefs = (assetId: string) =>
  req<ExternalRef[]>(`/api/assets/${assetId}/external-refs`);

export const addExternalRef = (assetId: string, body: AddExternalRefBody) =>
  postJson<ExternalRef>(`/api/assets/${assetId}/external-refs`, body);

export const deleteExternalRef = (refId: string) =>
  req<{ deleted: true }>(`/api/external-refs/${refId}`, { method: "DELETE" });

// ---------- Agent context pack (ADR-0019) ----------

export interface ContextPackQuery {
  wp: string;
  /** Omitted: the server default, `openproject`. */
  system?: ContextSystem;
  ancestors?: string[];
  /** OP project identifier or ICS project slug. */
  project?: string;
  depth?: number;
  budgetTokens?: number;
  include?: ContextInclude[];
}

/** Query string of `GET /api/context`; shared with the agent view, which shows it. */
export function contextPackQuery(q: ContextPackQuery): string {
  const p = new URLSearchParams({ wp: q.wp });
  if (q.system) p.set("system", q.system);
  if (q.ancestors?.length) p.set("ancestors", q.ancestors.join(","));
  if (q.project) p.set("project", q.project);
  if (q.depth !== undefined) p.set("depth", String(q.depth));
  if (q.budgetTokens !== undefined) p.set("budget_tokens", String(q.budgetTokens));
  for (const inc of q.include ?? []) p.append("include", inc);
  return p.toString();
}

export const getContextPack = (q: ContextPackQuery) =>
  req<ContextPack>(`/api/context?${contextPackQuery(q)}`);
