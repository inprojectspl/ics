// Document metadata types (ADR-0015), re-exported from `types.ts`.

/** Whether a document can be relied on, computed per viewer (ADR-0015). */
export type Freshness = "current" | "review_overdue" | "superseded";
type SummarySource = "human" | "agent";
/** Warnings that do not exclude a `Freshness` value. */
export type AssetFlag = "summary_stale" | "basis_changed";
/** Key of an admin-managed doc type; data from the API, so not a union. */
export type DocType = string;

/** `GET /api/doc-types` row; `label` is already in the caller's locale. */
export type DocTypeInfo = {
  key: DocType;
  label: string;
  agent_hint: string | null;
  default_review_days: number | null;
  properties_schema: Record<string, unknown>;
  position: number;
  archived: boolean;
  archived_at: string | null;
};

/** Admin view of a doc type: both stored labels, for editing. */
export type AdminDocType = DocTypeInfo & { label_pl: string; label_en: string };

export type DocTypeCreate = {
  key: DocType;
  label_pl: string;
  label_en: string;
  agent_hint?: string | null;
  default_review_days?: number | null;
  properties_schema?: Record<string, unknown>;
  position?: number;
};

/** Omitted fields stay unchanged; `archived` retires or restores the type. */
export type DocTypeUpdate = Partial<Omit<DocTypeCreate, "key">> & { archived?: boolean };

/** Person responsible for the content; the owner while none is set. */
type Maintainer = { id: string; email: string | null; display_name: string | null };

/** Document metadata carried by asset projections. There is no lifecycle status. */
export type AssetMetadata = {
  summary: string | null;
  summary_source: SummarySource | null;
  /** Content version the summary was written for. */
  summary_version: number | null;
  doc_type: DocType | null;
  freshness: Freshness;
  flags: AssetFlag[];
  /** Last content change (a new version, v1 included); `updated_at` also moves on metadata writes. */
  content_updated_at: string | null;
  maintainer: Maintainer | null;
  review_due_at: string | null;
  reviewed_at: string | null;
  language: string | null;
  properties: Record<string, unknown>;
  tags: string[];
};

/** `PATCH /api/assets/{id}/meta` body; omitted fields stay unchanged, null clears. */
export type AssetMetaPatch = Partial<{
  summary: string | null;
  doc_type: DocType | null;
  maintainer_id: string | null;
  review_due_at: string | null;
  language: string | null;
  properties: Record<string, unknown>;
}>;

/** Metadata block every asset projection carries (lists preview the summary). */
type MetadataBlock = Pick<
  AssetMetadata,
  "summary" | "summary_source" | "doc_type" | "freshness" | "flags" | "maintainer"
>;

/** `GET /api/assets/by-slug/{slug}/meta`: the full summary, viewer+. */
export type AssetMetaView = MetadataBlock & {
  id: string;
  slug: string;
  title: string | null;
  version: number;
  content_updated_at: string | null;
  tags: string[];
  project_id: string | null;
  access_role: "owner_file" | "project_owner" | "editor" | "viewer";
  /** Same values as `AssetMetaDetail`, so a reload shows what a save returned. */
  review_due_at: string | null;
  reviewed_at: string | null;
  language: string | null;
  properties: Record<string, unknown>;
};

/** Response of `PATCH /meta` and `POST /reviewed`. */
export type AssetMetaDetail = MetadataBlock & {
  id: string;
  version: number;
  summary_version: number | null;
  maintainer_id: string | null;
  review_due_at: string | null;
  reviewed_at: string | null;
  reviewed_by: string | null;
  language: string | null;
  properties: Record<string, unknown>;
};

/** Hygiene lists of a project (ADR-0015, ADR-0016); `duplicates` only when
 * the server reports it. */
export type HygieneList =
  | "no_summary"
  | "summary_stale"
  | "no_doc_type"
  | "review_overdue"
  | "basis_changed"
  | "superseded_linked"
  | "hidden_edges"
  | "duplicates";

export type HygieneItem = {
  id: string;
  slug: string;
  title: string | null;
  kind: string;
  doc_type: DocType | null;
  version: number;
  summary_version: number | null;
  review_due_at: string | null;
  content_updated_at: string | null;
  /** Only on `hidden_edges`: edges to documents the viewer cannot see. */
  hidden_edges?: number;
};

/** Row of the `duplicates` list: a suggested pair, `a.id < b.id`. */
export type DuplicatePair = {
  certainty: "certain" | "candidate";
  similarity: number;
  a: { id: string; slug: string; title: string | null };
  b: { id: string; slug: string; title: string | null };
};

/** `GET /api/projects/{slug}/hygiene?list=&page=`: every counter plus one page. */
export type ProjectHygiene = {
  project: { id: string; slug: string; name: string };
  /** Documents per list; `hidden_edges` counts edges. */
  counters: Partial<Record<HygieneList, number>>;
  list: HygieneList;
  page: number;
  page_size: number;
  total: number;
  /** Documents, or suggested pairs on `duplicates`. */
  items: Array<HygieneItem | DuplicatePair>;
};
