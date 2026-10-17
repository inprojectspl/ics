// Relation graph types (ADR-0016), re-exported from `types.ts`.

import type { AssetKind } from "./types";
import type { AssetFlag, DocType, Freshness } from "./metadataTypes";

/** Relation vocabulary of `asset_relations`, stored in its canonical direction. */
export type RelationType =
  | "derived_from"
  | "supersedes"
  | "depends_on"
  | "part_of"
  | "references"
  | "relates_to"
  | "duplicates"
  | "contradicts";

/** Every relation type, in the order the add dialog offers them. */
export const RELATION_TYPES: readonly RelationType[] = [
  "derived_from",
  "supersedes",
  "depends_on",
  "part_of",
  "references",
  "relates_to",
  "duplicates",
  "contradicts",
];

/** Who created an edge; informational only. */
export type RelationOrigin = "manual" | "agent" | "extracted" | "integration";

/** Group key of a relation list: the type when outgoing, its inverse when incoming. */
export type RelationLabel =
  | RelationType
  | "basis_for"
  | "superseded_by"
  | "required_by"
  | "has_part"
  | "referenced_by"
  | "duplicated_by";

/** Which end of an edge the asset in view is. */
export type RelationDirection = "out" | "in";

export type RelationEdge = {
  id: string;
  relation_type: RelationType;
  source_id: string;
  target_id: string;
  source_path: string | null;
  target_path: string | null;
  target_anchor: string | null;
  /** Target version when the edge was made; `target_changed` when it moved on. */
  target_version: number | null;
  target_version_now: number | null;
  target_changed: boolean;
  note: string | null;
  origin: RelationOrigin;
  created_at: string | null;
};

/** The other end of an edge as the viewer sees it; the summary is a preview. */
export type RelationNode = {
  id: string;
  slug: string;
  title: string | null;
  kind: AssetKind;
  doc_type: DocType | null;
  freshness: Freshness;
  summary: string | null;
  estimated_tokens: number | null;
};

export type RelationItem = RelationEdge & { other: RelationNode; label: RelationLabel };

/** `GET /api/assets/by-slug/{slug}/relations`. Symmetric edges are listed once. */
export type RelationList = {
  asset_id: string;
  outgoing: Partial<Record<RelationLabel, RelationItem[]>>;
  incoming: Partial<Record<RelationLabel, RelationItem[]>>;
};

export type NeighbourhoodNode = RelationNode & {
  depth: number;
  /** The viewer has graph access to it, so it can be expanded further. */
  expandable: boolean;
};

/** `GET /api/assets/by-slug/{slug}/neighbourhood`. */
export type Neighbourhood = {
  root_id: string;
  depth: number;
  types: RelationType[];
  nodes: NeighbourhoodNode[];
  edges: RelationEdge[];
  truncated: boolean;
  max_nodes: number;
};

/** One step of `GET /api/assets/by-slug/{slug}/path`: a project (only first) or a document. */
export type GraphPathStep =
  | { kind: "project"; id: string; slug: string }
  | { kind: "doc"; id: string; slug: string; title: string | null };

/** `GET /api/assets/by-slug/{slug}/path`: from a start on screen to the document; null when none. */
export type GraphPath = { path: GraphPathStep[] | null };

/** `POST /api/assets/{id}/relations`: the target by id or by slug. */
export type AddRelationBody = {
  relation_type: RelationType;
  target_id?: string;
  target_slug?: string;
  source_path?: string | null;
  target_path?: string | null;
  target_anchor?: string | null;
  note?: string | null;
};

/** `PATCH /api/relations/{id}`: `refresh_target_version` clears `target_changed`. */
export type PatchRelationBody = {
  note?: string | null;
  refresh_target_version?: boolean;
};

/** Node of `GET /api/projects/{slug}/graph`: a project document or, when
 * `external`, a document outside the project that an edge reaches. */
export type ProjectGraphNode = RelationNode & {
  superseded_by: { id: string; slug?: string; title?: string | null } | null;
  content_updated_at: string | null;
  external: boolean;
};

/** A unit of work (work package, backlog node) linked to project documents. */
export type ProjectTask = {
  /** `system:entity:external_id`. */
  id: string;
  system: string;
  entity: string;
  external_id: string;
  external_scope: string | null;
  label: string | null;
  url: string | null;
};

export type ProjectTaskLink = {
  task_id: string;
  asset_id: string;
  role: string;
  required: boolean;
};

/** `GET /api/projects/{slug}/graph[?include=tasks]`. */
export type ProjectGraph = {
  project: { id: string; slug: string; name: string };
  nodes: ProjectGraphNode[];
  edges: RelationEdge[];
  truncated: boolean;
  max_nodes: number;
  /** Only with `include=tasks`. */
  tasks?: ProjectTask[];
  task_links?: ProjectTaskLink[];
};

/** External systems a project can be mapped to (ADR-0018). */
type ProjectExternalSystem = "openproject" | "project_standard";

export type ProjectExternalRef = { system: ProjectExternalSystem; external_id: string };

/** Ordered key document of a project; hidden documents are left out by the server. */
export type KeyDocument = RelationNode & {
  asset_id: string;
  position: number;
  reason: string | null;
};

export type KeyDocumentIn = { asset_id: string; reason: string | null };

type OutlineHeading = { level: number; text: string; line: number; anchor: string };

/** `GET /by-slug/{slug}/outline`: headings of a document, or per file of a
 * collection. `status: "building"` (HTTP 202) while the outline is computed. */
export type AssetOutline = {
  kind?: AssetKind;
  headings?: OutlineHeading[];
  files?: { path: string; title?: string; headings?: OutlineHeading[] }[];
  status?: "building";
};

/** What a task needs a document for (ADR-0018). */
export type ExternalRefRole = "context" | "deliverable" | "reference";
type ExternalSystem = "openproject" | "project_standard" | "gitlab" | "url";
type ExternalEntity =
  | "work_package"
  | "project"
  | "version"
  | "node"
  | "merge_request"
  | "page";

/** `GET /api/assets/{id}/external-refs` row. `label` is plain text from the server. */
export type ExternalRef = {
  id: string;
  asset_id: string;
  system: ExternalSystem;
  entity: ExternalEntity;
  external_id: string;
  external_scope: string | null;
  role: ExternalRefRole;
  required: boolean;
  label: string | null;
  url: string | null;
  asset_path: string | null;
  pinned_version: number | null;
  /** The document moved past `pinned_version`. */
  basis_changed: boolean;
  note: string | null;
  origin: "manual" | "agent" | "integration";
  created_at: string | null;
};

export type AddExternalRefBody = {
  system: ExternalSystem;
  entity: ExternalEntity;
  external_id: string;
  external_scope?: string | null;
  role?: ExternalRefRole;
  required?: boolean;
  label?: string | null;
  url?: string | null;
  asset_path?: string | null;
  pinned_version?: number | null;
  note?: string | null;
};

// ---------- Agent context pack (ADR-0019) ----------

export type ContextSystem = "openproject" | "project_standard";
export type ContextInclude = "references" | "deliverables";

/** One way a document got into the pack; a document lists every way. */
export type ContextVia =
  | { kind: "direct"; role: ExternalRefRole; required: boolean }
  | { kind: "inherited"; wp: string; role: ExternalRefRole; required: boolean }
  | { kind: "project_key"; reason: string | null }
  | { kind: "successor_of"; slug: string; required: boolean }
  | { kind: "neighbour"; from: string; type: RelationLabel };

/** A listed document in the compact graph shape (ADR-0016, section 10): a
 * field that is empty or at its default is left out. */
export type ContextPackDocument = {
  slug: string;
  title: string | null;
  summary?: string;
  doc_type?: DocType;
  /** Left out for `md_single`. */
  kind?: AssetKind;
  version: number;
  /** Left out while `current`. */
  freshness?: Freshness;
  flags?: AssetFlag[];
  required?: true;
  via: ContextVia[];
  estimated_tokens?: number;
  /** Present only as `false`. */
  has_outline?: false;
  collapsed?: undefined;
};

/** A superseded document collapsed to one line, pointing at its successor's slug. */
export type ContextPackCollapsed = {
  slug: string;
  title: string | null;
  freshness: "superseded";
  collapsed: true;
  superseded_by: string;
  required?: true;
};

/** A server warning as data; the client words it by `code`. */
export type ContextPackWarning =
  | { code: "superseded"; params: { slug: string; successor: string; required: boolean } }
  | { code: "basis_changed"; params: { slug: string } }
  | { code: "contradicts"; params: { from: string; to: string } }
  | { code: "project_unmapped"; params: { project: string } }
  | { code: "task_unlinked"; params: { system: string; wp: string } };

/** What the budget cut and what it takes to get it. */
export type ContextPackTruncated = {
  documents: number;
  neighbours: number;
  /** Size of the pack with nothing cut. */
  needed_tokens: number;
  max_budget_tokens: number;
  /** A listed document to explore when neighbours were cut. */
  seed: string | null;
};

/** Extras of a compact edge, each present only when set; `changed` is
 * `[recorded target version, current target version]`. */
type CompactEdgeExtra = {
  id?: string;
  source_path?: string;
  target_path?: string;
  target_anchor?: string;
  note?: string;
  changed?: [number, number];
};

/** `[from, type, to]` or `[from, type, to, extras]`, ends by slug. */
type ContextPackEdge =
  | [from: string, type: RelationType, to: string]
  | [from: string, type: RelationType, to: string, extra: CompactEdgeExtra];

/** `GET /api/context`: the documents of one task, cut to the token budget. */
export type ContextPack = {
  project: { slug: string; name: string; external: string | null } | null;
  task: { system: ContextSystem; wp: string; ancestors: string[] };
  /** Agent hint per document type of the listed documents, once per type. */
  doc_types?: Partial<Record<DocType, string>>;
  documents: (ContextPackDocument | ContextPackCollapsed)[];
  edges: ContextPackEdge[];
  warnings: ContextPackWarning[];
  truncated: ContextPackTruncated | null;
  /** Size of this response, counted the way the budget is. */
  estimated_tokens: number;
  /** Documents of the task the caller cannot see (owners of the mapped project only). */
  hidden_count?: number;
};
