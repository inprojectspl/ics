// Fixtures shared by the explorer tests.
import type { RelationEdge, RelationType } from "../../api/types";
import { RELATION_TYPES } from "../../api/relationTypes";
import type { DocItem, Loaded, ProjectItem } from "./explorerTree";

export const ALL: ReadonlySet<RelationType> = new Set(RELATION_TYPES);

export function doc(id: string, over: Partial<DocItem> = {}): DocItem {
  return {
    kind: "doc",
    id,
    slug: `s${id}`,
    title: `Doc ${id}`,
    doc_type: null,
    freshness: "current",
    summary: null,
    expandable: true,
    ...over,
  };
}

export function project(slug: string, documents = 0): ProjectItem {
  return { kind: "project", id: `project:${slug}`, slug, name: `Project ${slug}`, documents };
}

export function rel(id: string, source: string, target: string, type: RelationType = "references"): RelationEdge {
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

/** A neighbourhood of `centre`: one edge from it to every other node. */
export function star(centre: string, others: string[], type: RelationType = "references"): Loaded {
  return {
    nodes: [doc(centre), ...others.map((o) => doc(o))],
    edges: others.map((o) => rel(`${centre}-${o}`, centre, o, type)),
  };
}
